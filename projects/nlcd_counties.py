"""
Create a US cost surface layer based on NLCD land use type and county.

1) Get 2016 NLCD raster.
    - s3-us-west-2.amazonaws.com/mrlc/NLCD_2016_Land_Cover_L48_20190424.zip
    - 30 meter resolution.
    - This has a unique Albers Concical Equal Area projection and under
      referenced. Try projecting to WGS 84 with nearest neighbor to maintain
      NLCD category values and match other data sets.
2) Create a second NLCD raster layer with only these three values:
    - 52: "SHRUB/SCRUB"
    - 81: "PASTURELAND"
    - 82: "CROPLAND"
3) Get County and State Shapefiles.
    - We need the State and County FIPS codes and names
4) Rasterize a State + County FIPS code to the same geometry as the NLCD
   raster above:
    - Might need to concatenate these values.
5) Multiply these rasters together:
    - This works because the products create all unique values.
    - Double check this.
6) Associate each product value with its State-County-NLCD combination and
   create a product-combination table.
7) Get a land-value table with price, State-County-NLCD combinations, and
   index values.
8) Join that land value table with the product table.
9) Map the land value table's index to the product raster to create a newcylinder charge fire-powered charger
   raster of land value indices.
10) At some point we will need an acre grid of land-values. How will we decide
    which land-values from the 30m grid to assign to acre grid cell?

"""
import geopandas as gpd
import numpy as np
import os
import pandas as pd
import rasterio
import subprocess as sp
import xarray as xr
from weto.functions import rasterize, Data_Path

# Data Path
# dp = Data_Path("/scratch/twillia2/weto/data")
dp = Data_Path("~/Box/WETO 1.2/data")

# Add in Translation to wgs 84
# ...

# Add in calc for 52, 81, and 82
# ...

# get the target geometry
nlcd = rasterio.open(dp.join("rasters/nlcd_2016_ag.tif"))
geom = nlcd.get_transform()
ny = nlcd.height
nx = nlcd.width
xs = [geom[0] + geom[1] * i  for i in range(nx)]
ys = [geom[3] + geom[-1] * i  for i in range(ny)]
extent = [np.min(xs), np.min(ys), np.max(xs), np.max(ys)]

# The geoid is a combo of state and county fips - progress?
if not os.path.exists(dp.join("rasters/county_gids.tif")):
    rasterize(src=dp.join("shapefiles/USA/tl_2017_us_county.shp"),
              dst=dp.join("rasters/county_gids.tif"),
              attribute="GEOID",
              resolution=geom[1],
              cols=nx,
              rows=ny,
              epsg=4326,
              extent=extent,
              overwrite=True)

# Multiply together - progress? how to catch stdout live?
if not os.path.exists(dp.join("rasters/agcounty_product.tif")):
    sp.call(["gdal_calc.py",
             "-A", dp.join("rasters/county_gids.tif"),
             "-B", dp.join("rasters/nlcd_2016_ag.tif"),
             "--outfile=" + dp.join("rasters/agcounty_product.tif"),
             "--NoDataValue=-9999.",
             "--calc=(A*B)"],
            stdout=sp.PIPE,
            stderr=sp.PIPE)

# We'll need both county and state names
cdf = gpd.read_file(dp.join("shapefiles/USA/tl_2017_us_county.shp"))
states = gpd.read_file(dp.join("shapefiles/USA/tl_2017_us_state.shp"))

# if the product of these two sets of values results in all unique values...
uags = np.array([52, 81, 82])
ugids = cdf["GEOID"].unique().astype(int)
ufips = cdf["COUNTYFP"].unique().astype(int)

# Are geoid (state+county fips) products unique?
product = []
for uag in uags:
    vals = uag * ugids
    vals = list(vals)
    product += vals

try:
    assert np.unique(np.array(product)).shape[0] == len(product)  # yes
    print("GEOID-NLCD products are all unique")
except AssertionError:
    print("GEOID-NLCD products are not all unique")

# Are county fips products unique?
product = []
for uag in uags:
    vals = uag * ufips
    vals = list(vals)
    product += vals

try:
    assert np.unique(np.array(product)).shape[0] == len(product)  # no
    print("County-NLCD products are all unique")
except AssertionError:
    print("County FIPS-NLCD products are not all unique")

# These are the values we need to associate with
lookup = pd.read_csv(dp.join("tables/conus_cbe_lookup.csv"))
lookup.columns = ['index', 'type',' dollar_ac']

# So we need a table with agid (ag + gid) associated values
states = states[["STATEFP", "NAME"]]
counties = cdf[["GEOID", "NAME", "NAMELSAD", "STATEFP", "COUNTYFP"]]
reference = pd.merge(counties, states, on="STATEFP")
reference.columns = ['GEOID', 'NAMECTY', 'NAMELSAD', 'STATEFP', 'COUNTYFP',
                     'NAMEST']

# We a column with COUNTY STATE AGTYPE, all caps
capper = lambda x: x["NAMECTY"].upper() + " " + x["NAMEST"].upper()
reference["type"] = reference[["NAMECTY", "NAMEST"]].apply(capper, axis=1)
reference = reference[["GEOID", "type"]]

# Now we need every combination of ag and type (3*n counties)
nlcd_codes = [52, 81, 82]
nlcd_legends = ["SHRUB/SCRUB", "PASTURELAND", "CROPLAND"]
ref_dfs = [reference.copy() for i in range(3)]
for i in range(3):
    ref_dfs[i]["nlcd"] = nlcd_codes[i]
    ref_dfs[i]["legend"] = nlcd_legends[i]
reference = pd.concat(ref_dfs, sort=True)
reference["type"] = reference["type"] + " " + reference["legend"]
reference["rast_val"] = (reference["GEOID"].astype(int) *
                         reference["nlcd"].astype(int))
reference.to_csv(dp.join("tables/nlcd_rast_lookup.csv"), index=False)

# Now join the lookup to the reference using the type field
reference = pd.merge(reference, lookup, on="type")
map_vals = dict(zip(reference["rast_val"], reference["index"]))
map_vals[0] = 0

# Now, can we map this index value to the agcounty_product raster?
def mapping(v, m):
    """map dictionary values (m) to xarray data array values (v)"""
    mapit = lambda x, y: y[x]
    return xr.apply_ufunc(mapit, v, m)
agcounty = xr.open_rasterio(dp.join("rasters/agcounty_product.tif"))[0, :, :]
index_raster = mapping(map_vals, agcounty)



# sample
test = agcounty[0, 50000:50500, 50000:50500].data
testout = np.vectorize(map_vals.get)(test)



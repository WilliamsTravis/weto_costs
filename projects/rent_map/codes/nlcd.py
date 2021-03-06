"""
Create a US cost surface layer based on NLCD land use type and county.
run exclusions.py first and use that as a template geometry.



1) Get 2016 NLCD raster.
    - s3-us-west-2.amazonaws.com/mrlc/NLCD_2016_Land_Cover_L48_20190424.zip
    - 30 meter resolution.
    - This has a unique Albers Concical Equal Area projection and under
      referenced. Try projecting to WGS 84 with nearest neighbor before
      reprojecting to our Alber's Equal Area projection.
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
6) Associate each product value with its State-County-NLCD combination and
   create a product-combination table.
7) Get a land-value table with price, State-County-NLCD combinations, and
   index values.
8) Join that land value table with the product table.
9) Map the land value table's index to the product raster to create a new
   raster of land value indices.
10) At some point we will need an acre grid of land-values. How will we decide
    which land-values from the 30m grid to assign to acre grid cell?

"""

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import subprocess as sp
from gdalmethods import warp, rasterize, Data_Path, reproject_polygon
from gdalmethods import Map_Values, tile_raster
from osgeo import ogr

# paths
# dp = Data_Path("~/Box/WETO 1.2/data")
dp = Data_Path("/scratch/twillia2/weto/data")
template_path = dp.join("rasters/albers/acre/rent_exclusions.tif")
nlcd_img_path = dp.join("rasters/NLCD/NLCD_2016_Land_Cover_L48_20190424.img")
nlcd_tif_path = dp.join("rasters/NLCD/NLCD_2016_Land_Cover_L48_20190424.tif")
nlcd_acre_path = dp.join("rasters/albers/acre/nlcd.tif")
nlcd_acre_ag_path = dp.join("rasters/albers/acre/nlcd_ag.tif")
county_path = dp.join("shapefiles/USA/tl_2017_us_county.shp")
county_acre_path = dp.join("rasters/albers/acre/county_gids.tif")
county_wgs_path = dp.join("shapefiles/USA/wgs/tl_2017_us_county.shp")
county_albers_path = dp.join("shapefiles/USA/albers/tl_2017_us_county.shp")
ag_product_path = dp.join("rasters/albers/acre/agcounty_product.tif")

# Template for geometries
template = rasterio.open(template_path)

# Translate .img format to .tif
sp.call(["gdal_translate",
         nlcd_img_path,
         nlcd_tif_path,
         "-b", "1",
         "-of", "GTiff",
         "-co", "compress=deflate"])

# Warp to acre resolution in the exclusions srs
warp(nlcd_tif_path,
     nlcd_acre_path,
     template=template_path,
     dtype= "byte",
     compress="deflate",
     overwrite=True)

# Add in calc for 52, 81, and 82
sp.call(["gdal_calc.py",
         "-A", nlcd_acre_path,
         "--outfile=" + nlcd_acre_ag_path,
         "--calc=(52*(A==52))+(81*(A==81))+(82*(A==82))",
         "--co", "compress=DEFLATE",
         "--NoDataValue=-9999.",
         "--type=Float32",
         "--overwrite"])

# Now reproject and rasterize the county polygons - to wgs first, then albers
shp = ogr.Open(county_path)
layer = shp.GetLayer()
s_srs = layer.GetSpatialRef()
s_srs = s_srs.ExportToProj4()
t_srs1 = "+proj=longlat +datum=WGS84 +no_defs"
t_srs2 = template.crs.to_proj4()
reproject_polygon(src=county_path, dst=county_wgs_path, t_srs=t_srs1)
reproject_polygon(src=county_wgs_path, dst=county_albers_path, t_srs=t_srs2)

# The geoid is a combo of state and county fips - progress?
rasterize(src=county_albers_path,
          dst=county_acre_path,
          attribute="GEOID",
          template_path=template_path,
          navalue=-9999.,
          dtype="Float32",
          overwrite=True)

# Multiply together
sp.call(["gdal_calc.py",
         "-A", county_acre_path,
         "-B", nlcd_acre_ag_path,
         "--outfile=" + ag_product_path,
         "--NoDataValue=-9999.",
         '--calc=(A*B)'])

# We'll need both county and state names
cdf = gpd.read_file("https://www2.census.gov/geo/tiger/TIGER2017/" +
                    "COUNTY/tl_2017_us_county.zip")
states = gpd.read_file("https://www2.census.gov/geo/tiger/TIGER2017//STATE/" +
                       "tl_2017_us_state.zip")

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

# These are the values we need to associate with
lookup = pd.read_csv(dp.join("tables/conus_cbe_lookup.csv"))
lookup.columns = ['code', 'type',' dollar_ac']

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

# Now join the lookup to the reference using the type field
reference = pd.merge(reference, lookup, on="type")
reference.to_csv(dp.join("tables/nlcd_rast_lookup.csv"), index=False)
mapvals = dict(zip(reference["rast_val"], reference["code"]))

# Split these into tiles
prod_files = tile_raster(
                    dp.join("rasters/albers/acre/agcounty_product.tif"),
                    out_folder=dp.join("rasters/albers/acre/product_tiles"),
                    ntiles=81, ncpu=15)

# Now, map the index values to the product values, write to new tiles
mt = Map_Values(mapvals)
outfolder = dp.join("rasters/albers/acre/nlcd_codes_tiles")
infolder = dp.join("rasters/albers/acre/product_tiles")

# I think I need to split this up, no luck yet with fancier methods
prod_file = dp.join("rasters/albers/acre/agcounty_product.tif")
outfile = dp.join("rasters/albers/acre/nlcd_codes.tif")
files = mt.map_files(src_files=prod_files, out_folder=outfolder, ncpu=15)  # <- Output geometry is slightly off

# Use gdal_merge to merge them back into a single raster
call =  ["gdal_merge.py", "-o", outfile] + files
sp.call(call)

# Done.

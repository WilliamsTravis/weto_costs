#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create a coverage layer with exclusions.

1) full and partial exclusions...don't count partial exclusions.
2) NA's for non-CONUS pixels
3) 1 for codes and for full exclusions
4) 0 for no codes and for partial exclusions

Created on Sun Feb  9 22:33:54 2020

@author: twillia2
"""
import numpy as np
import dask.array as da
import os
import numpy
import subprocess as sp
import xarray as xr
from weto.functions import gmask
from weto.gdalmethods import Data_Path, warp, to_raster
# from pygds.gdalmethods import Data_Path, warp, to_raster
from osgeo import gdal

# Data path
# dp = Data_Path("/Users/twillia2/Box/WETO 1.2/data")
dp = Data_Path("~/github/weto/data")

# paths
conus_path = dp.join("rasters/albers/acre/conus.tif")
codes_path = dp.join("rasters/albers/acre/cost_codes_ac.tif")
excl_path = dp.join("rasters/albers/acre/exclusions_ac.tif")
incl_path = dp.join("rasters/albers/acre/inclusion_ac.tif")
coverage_path = dp.join("rasters/albers/acre/coverage.tif")

# Best chunk size?
chunks = {'band': 1, 'x': 5000, 'y': 5000}

# Create a CONUS mask
if not os.path.exists(conus_path):

    # Use the nlcd_2016 raster, that covers everything.
    src = dp.join("rasters/nlcd_2016.tif")
    dst = dp.join("rasters/albers/acre/nlcd_2016.tif")

    # Create the new nlcd file
    warp(src, dst, template=codes_path, dtype="Int32", src_nodata=0,
         dst_nodata=-9999, overwrite=True)

    # Create field of 1s and 0s using gdal_calc.py
    sp.call(["gdal_calc.py",
             "-A", dst,
             "--outfile", conus_path,
             "--type=", gdal.GDT_Float32,
             "--calc=((A*0)+1)",
             "--NoDataValue=-9999."])

# Create an inclusion raster (opposite of the exclusion with no partials)
if not os.path.exists(incl_path):

    # Read in exclusions layer
    excl = xr.open_rasterio(excl_path)[0].data

    # Remove 0.5 values
    excl[excl == 0.5] = 1

    # Generate the inverse of the resulting exlusions layer
    incl = (excl - 1) * -1

    # Mask by conus
    conus = xr.open_rasterio(conus_path)[0]
    conus = da.from_array(conus)
    incl = incl * conus

    # Save this to file
    incl = incl.compute()
    to_raster(incl, incl_path, template=codes_path, compress="deflate")

if not os.path.exists(coverage_path):
    # Read in our three rasters - xarray seems to expect at least one time dim
    codes = xr.open_rasterio(codes_path, chunks=chunks)[0].data
    incl = xr.open_rasterio(incl_path, chunks=chunks)[0].data

    # Now create the overall coverage layer with incl and codes
    incl[incl == -9999] = np.nan
    codes[codes > 0] = 1
    code_cov = codes + incl
    code_cov[code_cov > 1] = 1
    code_cov = code_cov.astype("uint16")
    to_raster(code_cov, coverage_path, dtype="uint16", template=codes_path,
              tiled=False, compress="deflate")




# The coverage will 1s for areas that are covered by codes or full exclusions,
# 0s for CONUS areas with no coverage, and nans for areas outside of CONUS.
coverage = xr.open_rasterio(coverage_path, chunks=chunks)[0].data
conus = xr.open_rasterio(conus_path, chunks=chunks)[0].data
conus = conus.astype("uint16")
coverage = coverage * conus
x = coverage[0, 0].compute()
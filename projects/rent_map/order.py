#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The order of things. I could just describe which scripts to use, or create
methods out of each one and import them all.

Created on Fri Feb 14 10:25:58 2020

@author: twillia2
"""

# Download data

# Rasterize and warp to acre grids
# 1 exclusions.py - Run this first so we can set the geometries with it
# 2 nlcd, blm, tribal, state

# Assign codes with lookup table

# Mask layers in order -> exclusions, federal, tribal, state, private

# Stack masked layers and take max

# Calculate Coverage

# Assign dollar values to codes
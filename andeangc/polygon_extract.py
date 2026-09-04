"""Raster-to-basin extraction, in the two shapes this pipeline needs.

`extract_attributes` collapses a raster to one number per basin and joins it on
as a column (notebook 06); `extract_timeseries` collapses a gridded time series
to one column per basin, keeping time (notebook 07).

They use different engines on purpose. `exactextract` is fast on large rasters
but has no time dimension, while `xagg` handles the time dimension. `xagg` does
not cache its area weights, so this module does — see `_weightmap`; that is what
makes the ERA5 aggregation affordable.
"""

import copy
import hashlib
from collections import OrderedDict

import geopandas as gpd
import numpy as np
import pandas as pd
import xagg as xa  # faster for large netcdf files
import xarray as xr
from exactextract import exact_extract  # faster for large rasters
from xagg.classes import weightmap

xa.set_options(silent = True)

# Overlap weights, keyed by (grid, basins). nb07 aggregates 5 ERA5 variables on one
# grid and 3 variables per GCM on another, so without this the weights are rebuilt
# 5x and 3x identically. Bounded because every GCM brings its own grid.
_WEIGHTMAP_CACHE: OrderedDict[str, weightmap] = OrderedDict()
_WEIGHTMAP_CACHE_SIZE = 4


def _weightmap_key(raster: xr.DataArray, shapefile: gpd.GeoDataFrame) -> str:
    """Identify the (grid, basins) pair whose weights are being asked for.

    Hashing the coordinates and the geometries rather than trusting the caller
    is what makes the cache safe: `xagg` derives the pixel polygons from the
    lat/lon bounds alone (`create_raster_polygons` drops every data variable),
    so two calls agreeing on both hashes must produce identical weights, and any
    disagreement — a different variable's grid, a refiltered basin set — misses
    the cache and recomputes.
    """
    digest = hashlib.blake2b(digest_size=16)
    for dim in ("lat", "latitude", "y", "lon", "longitude", "x"):
        if dim in raster.coords:
            digest.update(dim.encode())
            digest.update(np.ascontiguousarray(raster[dim].values).tobytes())
    digest.update(b"".join(shapefile.geometry.to_wkb()))
    return digest.hexdigest()


def _weightmap(raster: xr.DataArray, shapefile: gpd.GeoDataFrame) -> weightmap:
    """The overlap weights for this (grid, basins) pair, computed at most once.

    Returns a copy, not the cached object: `xagg.aggregate` writes its result
    into `wm.agg` as a column named after the variable, so handing out the
    original would accumulate one time series per call inside the cache.
    """
    key = _weightmap_key(raster, shapefile)

    if key not in _WEIGHTMAP_CACHE:
        _WEIGHTMAP_CACHE[key] = xa.pixel_overlaps(raster, shapefile, impl='for_loop', silent=True)
        while len(_WEIGHTMAP_CACHE) > _WEIGHTMAP_CACHE_SIZE:
            _WEIGHTMAP_CACHE.popitem(last=False)
    _WEIGHTMAP_CACHE.move_to_end(key)

    cached = _WEIGHTMAP_CACHE[key]
    return weightmap(agg=copy.deepcopy(cached.agg), source_grid=cached.source_grid,
                     geometry=cached.geometry, overlap_da=cached.overlap_da,
                     weights=cached.weights)

def extract_attributes(raster: xr.DataArray | xr.Dataset | str,
                       shapefile: gpd.GeoDataFrame,
                       attributes: str | dict[str, str],
                       fun: str = "mean") -> gpd.GeoDataFrame:
    """Zonal statistics of one raster, joined onto the basins by gauge_id.

    `attributes` is either a column name — taken with `fun` — or a
    {column name: statistic} mapping, which is read in a single pass over the
    raster. Prefer the mapping when several statistics come from the same
    raster: three separate calls read it three times.
    """
    if isinstance(attributes, str):
        attributes = {attributes: fun}

    if isinstance(raster, str):
        raster = xr.open_dataset(raster)

    if raster.dims[0] == "lat" or raster.dims[0] == "lon":
        raster = raster.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=True)

    stats = list(dict.fromkeys(attributes.values()))  # unique, order preserved
    ds = exact_extract(raster.load(), shapefile, stats, include_cols=["gauge_id"],
                       output="pandas", progress=False)
    ds = ds.set_index("gauge_id")

    shape = shapefile
    for attribute_name, statistic in attributes.items():
        shape = shape.join(ds[statistic].rename(attribute_name), on="gauge_id")

    return shape

def extract_timeseries(raster: xr.DataArray, shapefile: gpd.GeoDataFrame) -> pd.DataFrame:
    """Area-weighted basin means of a gridded time series, one column per gauge.

    Returns a (time × gauge_id) frame carrying the basins' gauge ids as its
    columns, rounded to 3 decimals and stored as float32 — these frames are
    written straight to parquet, and the ERA5 stack is large enough that the
    dtype matters.

    The overlap weights are built once with the `for_loop` implementation and
    the aggregation then runs under `numba`: on the ~200 Andean basins the
    vectorised overlap path is the slower of the two. "Once" is literal — the
    weights are cached across calls on the (grid, basins) pair.
    """
    wm = _weightmap(raster, shapefile)
    ds = xa.aggregate(raster, wm, impl = "numba", silent = True)
    ds = ds.to_dataframe()[raster.name].unstack('poly_idx')
    ds.columns = shapefile.gauge_id
    ds.columns.name = None
    ds = ds.round(3).astype("float32")
    return ds

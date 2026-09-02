"""Raster-to-basin extraction, in the two shapes this pipeline needs.

`extract_attributes` collapses a raster to one number per basin and joins it on
as a column (notebook 06); `extract_timeseries` collapses a gridded time series
to one column per basin, keeping time (notebook 07).

They use different engines on purpose. `exactextract` is fast on large rasters
but has no time dimension, while `xagg` handles the time dimension and caches
the area weights, which is what makes the ERA5 aggregation affordable.
"""

import geopandas as gpd
import pandas as pd
import xagg as xa  # faster for large netcdf files
import xarray as xr
from exactextract import exact_extract  # faster for large rasters

xa.set_options(silent = True)

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
    vectorised overlap path is the slower of the two.
    """
    weightmap = xa.pixel_overlaps(raster, shapefile, impl='for_loop', silent=True)
    ds = xa.aggregate(raster, weightmap, impl = "numba", silent = True)
    ds = ds.to_dataframe()[raster.name].unstack('poly_idx')
    ds.columns = shapefile.gauge_id
    ds.columns.name = None
    ds = ds.round(3).astype("float32")
    return ds

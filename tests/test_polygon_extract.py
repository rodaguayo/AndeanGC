"""The cached overlap weights in `extract_timeseries`.

`xagg` rebuilds the pixel/polygon overlaps on every call, so the module caches
them on the (grid, basins) pair. Two things can go wrong with a cache like this
and neither would raise: it can hand back weights belonging to a *different*
grid or basin set, and — because `xagg.aggregate` writes its result into
`wm.agg` as a column — it can hand back a weightmap already carrying the
previous variable's time series. Both are pinned here.

The rasters are synthetic and tiny, so the expected basin means are worked out
by hand below rather than trusted from a previous run.
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import box

from andeangc import polygon_extract


@pytest.fixture(autouse=True)
def clear_cache():
    polygon_extract._WEIGHTMAP_CACHE.clear()
    yield
    polygon_extract._WEIGHTMAP_CACHE.clear()


def raster(name="prcp", values=None, lat=(0.5, 1.5, 2.5), lon=(10.5, 11.5, 12.5)):
    """A (time, lat, lon) grid whose values are 0, 1, 2, ... in reading order."""
    lat, lon = np.array(lat), np.array(lon)
    shape = (3, len(lat), len(lon))
    if values is None:
        values = np.arange(np.prod(shape), dtype="float64").reshape(shape)
    return xr.DataArray(values, name=name, dims=("time", "lat", "lon"),
                        coords={"time": pd.date_range("2000-01-01", periods=3),
                                "lat": lat, "lon": lon})


def basins(gauge_ids=("A", "B")):
    """A covers the one bottom-left pixel; B covers the four top-right ones."""
    geometry = [box(10.0, 0.0, 11.0, 1.0), box(11.0, 1.0, 13.0, 3.0)]
    return gpd.GeoDataFrame({"gauge_id": list(gauge_ids), "geometry": geometry}, crs="EPSG:4326")


def test_basin_means_are_area_weighted_and_keyed_by_gauge_id():
    out = polygon_extract.extract_timeseries(raster(), basins())

    # A is pixel 0 of each timestep; B is the mean of pixels 4, 5, 7, 8 -> 6.0
    assert list(out.columns) == ["A", "B"]
    assert out["A"].tolist() == [0.0, 9.0, 18.0]
    assert out["B"].tolist() == [6.0, 15.0, 24.0]
    assert out.dtypes.unique().tolist() == [np.dtype("float32")]


def test_second_variable_on_the_same_grid_reuses_the_weights_and_stays_correct():
    shape = basins()
    first = polygon_extract.extract_timeseries(raster("prcp"), shape)
    second = polygon_extract.extract_timeseries(raster("tasmax"), shape)

    assert len(polygon_extract._WEIGHTMAP_CACHE) == 1     # the grid was recognised
    pd.testing.assert_frame_equal(first, second)          # same values in, same values out

    # aggregate() appends a column per variable; the cached weightmap must not keep them
    cached = next(iter(polygon_extract._WEIGHTMAP_CACHE.values()))
    assert "prcp" not in cached.agg.columns
    assert "tasmax" not in cached.agg.columns


def test_a_different_grid_or_a_different_basin_set_misses_the_cache():
    polygon_extract.extract_timeseries(raster(), basins())

    polygon_extract.extract_timeseries(raster(lon=(10.4, 11.4, 12.4)), basins())   # same extent, shifted grid
    assert len(polygon_extract._WEIGHTMAP_CACHE) == 2

    polygon_extract.extract_timeseries(raster(), basins().iloc[:1])
    assert len(polygon_extract._WEIGHTMAP_CACHE) == 3


def test_shifting_one_basin_changes_the_weights():
    """Same grid, same gauge_ids, moved polygon — the geometry is part of the key."""
    shape = basins()
    reference = polygon_extract.extract_timeseries(raster(), shape)

    moved = shape.copy()
    moved.loc[0, "geometry"] = box(12.0, 2.0, 13.0, 3.0)   # A now sits on the top-right pixel
    out = polygon_extract.extract_timeseries(raster(), moved)

    assert len(polygon_extract._WEIGHTMAP_CACHE) == 2
    assert out["A"].tolist() == [8.0, 17.0, 26.0]          # pixel 8, not pixel 0
    assert reference["A"].tolist() == [0.0, 9.0, 18.0]


def test_the_cache_is_bounded():
    for i in range(polygon_extract._WEIGHTMAP_CACHE_SIZE + 3):
        shifted = raster(lon=(10.5 + i / 100, 11.5 + i / 100, 12.5 + i / 100))   # a new grid each time
        polygon_extract.extract_timeseries(shifted, basins())

    assert len(polygon_extract._WEIGHTMAP_CACHE) == polygon_extract._WEIGHTMAP_CACHE_SIZE

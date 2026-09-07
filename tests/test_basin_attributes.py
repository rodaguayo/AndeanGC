"""The LAI attributes, on a grid small enough to check by hand.

`lai_attributes` is the one attribute function whose source raster carries a
dimension — twelve climatological months — so the two things worth pinning are
that `lai_max`/`lai_diff` reduce over that dimension rather than over space, and
that a basin the source never retrieves comes out as NaN instead of zero. The
rest of `basin_attributes` needs `data_root` and is out of scope here; only the
directory is redirected, so the filename still comes from `config.yml`.
"""

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import box

from andeangc import basin_attributes as ba
from andeangc import config as cfg

# One month per row: the left column swings between 1 and 4, the right one is
# flat at 2, and the bottom-right pixel is never retrieved.
MONTHLY_LEFT = [1.0, 2.0, 4.0, 3.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0, 3.0, 2.0]


@pytest.fixture(autouse=True)
def lai_file(tmp_path, monkeypatch):
    """A (month, lat, lon) climatology in a redirected `data_dir('lai')`."""
    lat, lon = np.array([1.5, 0.5]), np.array([10.5, 11.5])  # north-up, as the real file is
    values = np.empty((12, 2, 2), dtype="float32")
    values[:, :, 0] = np.array(MONTHLY_LEFT)[:, None]
    values[:, 0, 1] = 2.0
    values[:, 1, 1] = np.nan  # unretrieved, e.g. a barren surface

    lai = xr.DataArray(values, name="lai", dims=("month", "lat", "lon"),
                       coords={"month": np.arange(1, 13), "lat": lat, "lon": lon})
    lai = lai.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs("EPSG:4326")

    path = tmp_path / cfg.inputs["lai_climatology"]
    lai.to_dataset().to_netcdf(path)
    monkeypatch.setattr(ba.cfg, "data_dir", lambda subdir: tmp_path)
    return path


def basins():
    """`left` is the left column, `flat` the top-right pixel, `void` the NaN one."""
    geometry = [box(10.0, 0.0, 11.0, 2.0), box(11.0, 1.0, 12.0, 2.0), box(11.0, 0.0, 12.0, 1.0)]
    return gpd.GeoDataFrame({"gauge_id": ["left", "flat", "void"], "geometry": geometry}, crs="EPSG:4326")


def test_max_and_amplitude_are_taken_over_the_months():
    out = ba.lai_attributes(basins()).set_index("gauge_id")

    # left: the monthly cycle, 1 -> 4. flat: 2 every month, so no amplitude.
    assert out.loc["left", "lai_max"] == pytest.approx(4.0)
    assert out.loc["left", "lai_diff"] == pytest.approx(3.0)
    assert out.loc["flat", "lai_max"] == pytest.approx(2.0)
    assert out.loc["flat", "lai_diff"] == pytest.approx(0.0)


def test_a_basin_the_source_never_retrieves_is_nan_not_zero():
    out = ba.lai_attributes(basins()).set_index("gauge_id")

    assert np.isnan(out.loc["void", "lai_max"])
    assert np.isnan(out.loc["void", "lai_diff"])


def test_the_input_geodataframe_is_left_untouched():
    shape = basins()
    ba.lai_attributes(shape)

    assert "lai_max" not in shape.columns


def test_basins_indexed_by_gauge_id_get_the_same_values():
    """`land_cover_attributes` runs first in nb06 and leaves the index set."""
    positional = ba.lai_attributes(basins()).set_index("gauge_id")
    indexed = ba.lai_attributes(basins().set_index("gauge_id"))

    pd.testing.assert_frame_equal(positional[["lai_max", "lai_diff"]], indexed[["lai_max", "lai_diff"]])

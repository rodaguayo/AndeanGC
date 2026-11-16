"""The CHELSA / ERA5 factors, on a 2x2 grid whose answers can be worked out by hand.

What is worth pinning is the order of the three rules, because each one undoes part of the
other: the cap clips the wet-biased months, the annual floor then raises a cell whose weighted
factor fell below 1 — which can push a month back over the cap — and the ocean mask resets
everything to 1 last. The four cells exercise one rule each. Inputs are synthetic GeoTIFFs in
`tmp_path`; nothing reads `data_root`.
"""

import numpy as np
import pandas as pd
import pytest
import rioxarray  # noqa: F401
import xarray as xr

from andeangc import precip_correction as pc

CAP = 2.5
LAT, LON = np.array([-1.0, -0.75]), np.array([10.0, 10.25])  # ascending, as the ERA5 file is


@pytest.fixture
def era5():
    """1 mm/day everywhere, every day of 2000-2001: a flat 1981-2010-style climatology."""
    time = pd.date_range("2000-01-01", "2001-12-31", freq="D")
    return xr.DataArray(np.ones((len(time), 2, 2)), dims=("time", "latitude", "longitude"),
                        coords={"time": time, "latitude": LAT, "longitude": LON}, name="prcp")


def climatology(era5):
    """The ERA5 mm/month climatology the factors divide by (February averages 28.5 days here)."""
    return era5.resample(time="MS").sum().groupby("time.month").mean().values[:, 0, 0]


def write_rasters(tmp_path, values, name):
    """One north-up 0.25° GeoTIFF per month (or a single one), 5x5 pixels per ERA5 cell."""
    paths = []
    for i, grid in enumerate(values):
        fine = np.kron(grid[::-1], np.ones((5, 5))).astype("float32")  # north up
        da = xr.DataArray(fine, dims=("y", "x"),
                          coords={"y": -0.65 - 0.05 * np.arange(10),
                                  "x": 9.875 + 0.05 * np.arange(10) + 0.025})
        da = da.rio.write_crs(4326).rio.write_nodata(np.nan)
        paths.append(tmp_path / f"{name}_{i:02d}.tif")
        da.rio.to_raster(paths[-1])
    return paths


def test_factor_rules(tmp_path, era5):
    days = climatology(era5)
    chelsa = np.empty((12, 2, 2))
    chelsa[:, 0, 0] = 1.5 * days                                  # plain ratio, untouched
    chelsa[:, 0, 1] = np.where(np.arange(12) == 0, 10, 1) * days  # Jan capped, the rest 1
    chelsa[:, 1, 0] = 0.5 * days                                  # drier than ERA5: floored to 1
    chelsa[:, 1, 1] = 0.5 * days                                  # ocean

    land = np.ones((1, 2, 2))
    land[0, 1, 1] = np.nan
    factor = pc.chelsa_era5_factors(write_rasters(tmp_path, chelsa, "chelsa"), era5,
                                    period=("2000-01-01", "2001-12-31"), cap=CAP,
                                    land=write_rasters(tmp_path, land, "dem")[0])

    f = factor.values
    np.testing.assert_allclose(f[:, 0, 0], 1.5, rtol=1e-5)
    assert f[0, 0, 1] == pytest.approx(CAP) and np.allclose(f[1:, 0, 1], 1)
    np.testing.assert_allclose(f[:, 1, 0], 1, rtol=1e-5)  # the floor rescales the whole cell
    np.testing.assert_array_equal(f[:, 1, 1], 1)
    assert "capped at 2.5" in factor.attrs["description"] and "(2000-2001)" in factor.attrs["description"]


def test_floor_respects_cap(tmp_path, era5):
    """Dividing by an annual factor below 1 must not leave a month above the cap."""
    days = climatology(era5)
    chelsa = np.repeat((np.where(np.arange(12) == 0, 2.4, 0.1) * days)[:, None, None], 4, axis=1).reshape(12, 2, 2)

    factor = pc.chelsa_era5_factors(write_rasters(tmp_path, chelsa, "chelsa"), era5,
                                    period=("2000-01-01", "2001-12-31"), cap=CAP)

    weights = days / days.sum()
    assert float(factor.max()) <= CAP + 1e-5
    assert (factor.values[:, 0, 0] * weights).sum() == pytest.approx(1, rel=1e-5)


def test_apply_monthly_factor(era5):
    factor = xr.DataArray(np.arange(1, 13, dtype="float32")[:, None, None] * np.ones((12, 2, 2)),
                          dims=("month", "latitude", "longitude"),
                          coords={"month": np.arange(1, 13), "latitude": LAT, "longitude": LON})
    out = pc.apply_monthly_factor(era5, factor)

    assert out.name == "prcp"
    assert float(out.sel(time="2000-03-15")[0, 0]) == 3
    assert float(out.sel(time="2001-12-31")[1, 1]) == 12

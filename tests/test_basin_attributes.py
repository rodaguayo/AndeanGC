"""The LAI attributes, on a grid small enough to check by hand.

`lai_attributes` is the one attribute function whose source raster carries a
dimension — twelve climatological months — so the first thing worth pinning is
that `lai_max`/`lai_diff` reduce over that dimension rather than over space. The
second is the barren-surface rule: GIMMS retrieves nothing over bare rock, ice
and desert, and those pixels have to count as zero leaf area rather than drop
out of the basin mean, which is what the `half` basin below checks.

`topographic_attributes` follows, on a synthetic ridge: what is worth pinning
there is that aspect is averaged as a unit vector rather than as a bearing, so
that opposite flanks cancel instead of summing to the direction between them.
The rest of `basin_attributes` needs `data_root` and is out of scope here; only
the directory is redirected, so the filenames still come from `config.yml`.
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
    """`left` is the left column, `flat` the top-right pixel, `void` the unretrieved one.

    `half` spans both right-hand pixels, so it is half retrieved and half not.
    """
    geometry = [box(10.0, 0.0, 11.0, 2.0), box(11.0, 1.0, 12.0, 2.0),
                box(11.0, 0.0, 12.0, 1.0), box(11.0, 0.0, 12.0, 2.0)]
    return gpd.GeoDataFrame({"gauge_id": ["left", "flat", "void", "half"], "geometry": geometry},
                            crs="EPSG:4326")


def test_max_and_amplitude_are_taken_over_the_months():
    out = ba.lai_attributes(basins()).set_index("gauge_id")

    # left: the monthly cycle, 1 -> 4. flat: 2 every month, so no amplitude.
    assert out.loc["left", "lai_max"] == pytest.approx(4.0)
    assert out.loc["left", "lai_diff"] == pytest.approx(3.0)
    assert out.loc["flat", "lai_max"] == pytest.approx(2.0)
    assert out.loc["flat", "lai_diff"] == pytest.approx(0.0)


def test_a_basin_the_source_never_retrieves_is_barren_not_missing():
    out = ba.lai_attributes(basins()).set_index("gauge_id")

    assert out.loc["void", "lai_max"] == pytest.approx(0.0)
    assert out.loc["void", "lai_diff"] == pytest.approx(0.0)


def test_unretrieved_pixels_are_averaged_in_as_zero_not_dropped():
    """Half of `half` is barren, so its basin mean is half the retrieved value.

    Excluding the barren pixel instead would report 2.0 — the mean LAI of the
    vegetated fraction, which is a different attribute.
    """
    out = ba.lai_attributes(basins()).set_index("gauge_id")

    assert out.loc["half", "lai_max"] == pytest.approx(1.0)


def test_the_input_geodataframe_is_left_untouched():
    shape = basins()
    ba.lai_attributes(shape)

    assert "lai_max" not in shape.columns


def test_basins_indexed_by_gauge_id_get_the_same_values():
    """`land_cover_attributes` runs first in nb06 and leaves the index set."""
    positional = ba.lai_attributes(basins()).set_index("gauge_id")
    indexed = ba.lai_attributes(basins().set_index("gauge_id"))

    pd.testing.assert_frame_equal(positional[["lai_max", "lai_diff"]], indexed[["lai_max", "lai_diff"]])


# --- topographic attributes -------------------------------------------------
#
# A north-south ridge, plus a flat block to its south. `RIDGE_DROP` per cell
# makes the west flank face due west (aspect 270) and the east flank due east
# (90); the crest itself has no gradient, so xrspatial marks it flat.
RIDGE_DROP = 100.0
CELL = 0.0025  # ~250 m at 33S, close to the real 270 m DEM
WEST, NORTH = -70.0, -32.97  # the north-west cell centre
CREST, SEAM = 6, 9  # column of the ridge crest; first row of the flat block


def cell_x(i):
    return WEST + CELL * i


def cell_y(j):
    return NORTH - CELL * j


def cells(i0, i1, j0, j1):
    """The box covering cells [i0, i1] x [j0, j1], edges included."""
    return box(cell_x(i0) - CELL / 2, cell_y(j1) - CELL / 2,
               cell_x(i1) + CELL / 2, cell_y(j0) + CELL / 2)


@pytest.fixture
def dem_file(tmp_path, monkeypatch):
    """The ridge, written where `topographic_attributes` will look for it."""
    monkeypatch.setattr(ba.cfg, "data_dir", lambda subdir: tmp_path)
    n = 13
    z = -RIDGE_DROP * np.abs(np.arange(n) - CREST)
    z = np.tile(z, (n, 1))
    z[SEAM:, :] = 0.0  # a flat block, to check flat cells are dropped

    dem = xr.DataArray(z, dims=("y", "x"),
                       coords={"y": cell_y(np.arange(n)), "x": cell_x(np.arange(n))})
    dem = dem.rio.write_crs("EPSG:4326")
    dem.rio.to_raster(tmp_path / cfg.inputs["dem_attributes"])
    return tmp_path


def flanks():
    """`east` and `west` are one flank each; `roof` is both, `flat` is neither.

    `roof` is the two flanks and not the crest between them: the crest cell has
    no gradient in lat/lon but picks one up when the DEM is reprojected, and the
    cancellation being checked there is about the flanks, not about it.
    """
    geometry = [cells(8, 9, 1, 3), cells(3, 4, 1, 3),
                cells(2, 5, 1, 4).union(cells(7, 10, 1, 4)), cells(3, 9, 10, 11)]
    return gpd.GeoDataFrame({"gauge_id": ["east", "west", "roof", "flat"], "geometry": geometry},
                            crs="EPSG:4326")


def test_a_single_flank_reads_as_the_direction_it_faces(dem_file):
    out = ba.topographic_attributes(flanks()).set_index("gauge_id")

    assert out.loc["east", "aspect_east"] == pytest.approx(1.0, abs=0.05)
    assert out.loc["east", "aspect_north"] == pytest.approx(0.0, abs=0.05)
    assert out.loc["west", "aspect_east"] == pytest.approx(-1.0, abs=0.05)
    assert out.loc["west", "aspect_north"] == pytest.approx(0.0, abs=0.05)


def test_opposite_flanks_cancel_instead_of_averaging_to_due_south(dem_file):
    """The reason aspect is published as components and not as a mean bearing.

    `roof` is half west-facing (270) and half east-facing (90). Averaged as
    bearings that is 180 — due south, a direction no cell in the basin faces,
    and it would read here as aspect_north = -1. As unit vectors the two flanks
    cancel, which is the honest answer: the basin has no preferred exposure.

    The tolerance is loose because the flanks cancel to a few hundredths rather
    than to zero: reprojecting a 13x13 grid to UTM cannot split its cells evenly
    between the two flanks. Real basins are thousands of cells wide.
    """
    out = ba.topographic_attributes(flanks()).set_index("gauge_id")

    assert out.loc["roof", "aspect_east"] == pytest.approx(0.0, abs=0.1)
    assert out.loc["roof", "aspect_north"] == pytest.approx(0.0, abs=0.1)


def test_a_flat_basin_has_no_direction_rather_than_facing_north(dem_file):
    """xrspatial marks flat cells -1, which would otherwise read as ~due north."""
    out = ba.topographic_attributes(flanks()).set_index("gauge_id")

    assert np.isnan(out.loc["flat", "aspect_north"])
    assert np.isnan(out.loc["flat", "aspect_east"])


def test_elevation_is_taken_from_the_dem_in_lat_lon(dem_file):
    """Only slope and aspect go through UTM; the elevation stats must not."""
    out = ba.topographic_attributes(flanks()).set_index("gauge_id")

    assert out.loc["east", "elev_mean"] == pytest.approx(-250.0)  # cells 8 and 9
    assert out.loc["flat", "elev_mean"] == pytest.approx(0.0)


# --- the GLEAM stack --------------------------------------------------------
#
# `gleam_reference_stack` is a loader, not an attribute function, so what is
# worth pinning is the three things it does that the ERA5 loader does not: it
# gathers one file per variable *and* year into a single stack, it cuts a global
# grid down to the basins, and it renames lat/lon so that the clip and
# `exact_extract` find the spatial dimensions. The evaporation attributes
# themselves stay in nb06 and are not tested here.
GLEAM_YEARS = (1989, 1990, 1991)
GLEAM_BASE = {"E": 100.0, "Ep": 1000.0}  # + the year, so every file is identifiable


@pytest.fixture
def gleam_files(tmp_path):
    """One file per variable and year, over a grid wider than the basins below."""
    lat, lon = np.array([1.5, 0.5]), np.array([10.5, 11.5, 12.5])  # north-up, as the real files are

    for year in GLEAM_YEARS:
        for variable, base in GLEAM_BASE.items():
            values = np.full((1, lat.size, lon.size), base + year, dtype="float32")
            field = xr.DataArray(values, name=variable, dims=("time", "lat", "lon"),
                                 coords={"time": [np.datetime64(f"{year}-12-31")], "lat": lat, "lon": lon})
            field.to_dataset().to_netcdf(tmp_path / cfg.inputs["gleam"].format(variable=variable, year=year))
    return tmp_path


def gleam_basins():
    """Two basins over the left-hand column, leaving the third one outside."""
    return gpd.GeoDataFrame({"gauge_id": ["left", "middle"],
                             "geometry": [box(10.0, 0.0, 11.0, 2.0), box(11.0, 0.0, 12.0, 2.0)]},
                            crs="EPSG:4326")


def test_both_variables_arrive_in_one_stack(gleam_files):
    """The archive splits E and Ep across files; the notebook wants one stack."""
    stack = ba.gleam_reference_stack(period=["1989-01-01", "1991-12-31"])

    assert set(stack.data_vars) == {"E", "Ep"}
    assert stack.sizes["time"] == len(GLEAM_YEARS)


def test_only_the_reference_period_is_kept(gleam_files):
    """GLEAM is stamped at year end, so a calendar-year slice must still catch it."""
    stack = ba.gleam_reference_stack(period=["1990-01-01", "1990-12-31"])

    assert stack.sizes["time"] == 1
    # .compute(): the stack comes back lazy, which is what nb06 aggregates on
    assert stack.E.mean().compute().item() == pytest.approx(GLEAM_BASE["E"] + 1990)
    assert stack.Ep.mean().compute().item() == pytest.approx(GLEAM_BASE["Ep"] + 1990)


def test_the_global_grid_is_cut_down_to_the_basins(gleam_files):
    """Without this the notebook reads every year of a global 0.1 degree grid."""
    stack = ba.gleam_reference_stack(gleam_basins(), period=["1990-01-01", "1990-12-31"])

    assert stack.sizes["x"] == 2  # the third column is outside the basins
    assert stack.sizes["y"] == 2


def test_the_axes_are_renamed_so_the_extraction_finds_them(gleam_files):
    """`clip_to` and `exact_extract` both work in x/y, GLEAM ships lat/lon."""
    stack = ba.gleam_reference_stack(period=["1990-01-01", "1990-12-31"])

    assert {"x", "y"} <= set(stack.dims)
    assert not {"lat", "lon"} & set(stack.dims)

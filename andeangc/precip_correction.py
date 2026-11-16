"""ERA5 precipitation correction with CHELSA V2.1 monthly factors (tools/correct_era5_chelsa.py).

CHELSA V2.1 is ERA5 downscaled to 1 km with orographic effects and corrected to GPCC, so the
ratio of its monthly climatology to the ERA5 climatology is a correction of ERA5 itself. The
factors are built once on the ERA5 0.25° grid and applied to the gridded ERA5 precipitation,
so every consumer (nb06's attributes, nb07's basin series, nb08's signatures) only needs the
corrected file.

Ported unchanged from Whatif-Andes (`src/climate.py`), which reads the same files under the
same `data_root`: the two projects must force their models with the same precipitation, so
the method is not this dataset's to change on its own. Its parameters are `prcp_factor_*` in
`config.yml`.

- `chelsa_era5_factors` builds ``pr_factor(month, latitude, longitude)``.
- `apply_monthly_factor` multiplies a daily or monthly series by the factor of its month.
- `factor_on_grid` carries the factor to the CMIP6 grid, offset by half a cell from ERA5.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import rioxarray as rio  # noqa: F401  (registers the .rio accessor)
import xarray as xr
from rasterio.enums import Resampling


def _to_raster_grid(da: xr.DataArray) -> xr.DataArray:
    """ERA5 layout (latitude, longitude; ascending) -> rioxarray layout (y, x; north up)."""
    da = da.rename({"latitude": "y", "longitude": "x"}).sortby("y", ascending=False)
    return da.rio.write_crs(4326)


def _from_raster_grid(da: xr.DataArray, like: xr.DataArray) -> xr.DataArray:
    """Inverse of `_to_raster_grid`, aligned to the coordinates of `like`."""
    da = da.drop_vars("spatial_ref", errors="ignore").rename({"y": "latitude", "x": "longitude"})
    return da.reindex(latitude=like.latitude, longitude=like.longitude, method="nearest", tolerance=1e-6)


def _years(period: Sequence[str]) -> str:
    """'1981-2010' from either years or full ISO dates."""
    return f"{period[0][:4]}-{period[1][:4]}"


def chelsa_era5_factors(chelsa_files: Sequence[str | Path],
                        prcp: xr.DataArray,
                        period: Sequence[str],
                        cap: float,
                        land: str | Path | None = None,
                        floor_period: Sequence[str] | None = None) -> xr.DataArray:
    """Monthly multiplicative factors CHELSA V2.1 / ERA5 on the ERA5 grid.

    1. ERA5 monthly climatology over `period` (mean of the monthly sums, mm month-1).
    2. CHELSA monthly climatologies (`chelsa_files`, January to December, 1 km) averaged onto
       the ERA5 cells.
    3. ``f_m = CHELSA_m / ERA5_m``, capped at `cap` (dry months with near-zero ERA5).
    4. Annual floor: in cells whose annual factor ``sum(f_m P_m) / sum(P_m)`` is below 1, all
       months are divided by it, so the annual total is not reduced and CHELSA's seasonal
       shape is kept. A per-month floor would raise the annual factor where nothing needs it.
       The weights ``P_m`` are the ERA5 climatology of `floor_period` (the period the
       correction is applied to); with the 1981-2010 weights, a shift in the seasonal cycle
       leaves some cells below 1 in 2000-2019 (down to 0.87). Floor and cap are applied
       alternately until both hold.
    5. ``f_m = 1`` over the ocean (no `land` DEM data in the cell, if given) and where the
       ratio is undefined.

    `prcp` is the daily ERA5 precipitation (dims time/latitude/longitude). Returns
    ``pr_factor`` with dims (month, latitude, longitude) on its coordinates.
    """
    monthly = prcp.sel(time=slice(*period)).resample(time="MS").sum()
    era5_clim = monthly.groupby("time.month").mean().load()

    template = _to_raster_grid(era5_clim.isel(month=0, drop=True))
    west, south, east, north = template.rio.bounds()

    if len(chelsa_files) != 12:
        raise ValueError(f"expected 12 monthly CHELSA files, got {len(chelsa_files)}")

    chelsa = []
    for path in chelsa_files:
        layer = rio.open_rasterio(path, masked=True, mask_and_scale=True).squeeze(drop=True)
        layer = layer.rio.clip_box(west - 0.5, south - 0.5, east + 0.5, north + 0.5)
        layer = layer.rio.reproject_match(template, resampling=Resampling.average)
        chelsa.append(_from_raster_grid(layer, era5_clim))
    chelsa_clim = xr.concat(chelsa, dim="month").assign_coords(month=np.arange(1, 13))

    # undefined ratios (no ERA5 precipitation in the period, no CHELSA data) -> 1 before the
    # floor: they still carry weight in the floor-period climatology
    factor = (chelsa_clim / era5_clim).where(era5_clim > 0).fillna(1.0).clip(max=cap)

    if floor_period is None:
        weights = era5_clim
    else:
        weights = (prcp.sel(time=slice(*floor_period)).resample(time="MS").sum()
                   .groupby("time.month").mean().load())
    # Floor and cap together: dividing by an annual factor < 1 can push months above the cap
    # (hyper-arid cells, up to ~14 in one pass), so alternate floor and cap until both hold.
    # Capped months stay at the cap and the remaining months absorb the floor.
    for _ in range(50):
        annual = (factor * weights).sum("month") / weights.sum("month")
        if bool((annual >= 1 - 1e-6).all()) and bool((factor <= cap).all()):
            break
        factor = (factor / annual.clip(max=1)).clip(max=cap)
    else:
        raise RuntimeError("annual floor and monthly cap did not converge")

    if land is not None:
        dem = rio.open_rasterio(land, masked=True).squeeze(drop=True)
        is_land = dem.notnull().astype("float32").rio.write_nodata(np.nan)
        is_land = is_land.rio.reproject_match(template, resampling=Resampling.average)
        factor = factor.where(_from_raster_grid(is_land, era5_clim) > 0)

    factor = factor.fillna(1.0).astype("float32").rename("pr_factor")
    factor.attrs = dict(
        long_name="Monthly multiplicative ERA5 precipitation factor",
        units="1",
        description=(f"CHELSA V2.1 / ERA5 monthly climatologies ({_years(period)}), "
                     f"CHELSA averaged to the ERA5 grid, capped at {cap}, annual floor at 1 "
                     f"(weighted by ERA5 {_years(floor_period or period)}), "
                     "1 over the ocean and where undefined"),
    )
    return factor


def factor_on_grid(factor: xr.DataArray, lat: xr.DataArray, lon: xr.DataArray) -> xr.DataArray:
    """Bilinear interpolation of the factor to another regular grid, renamed to ``lat``/``lon``.

    Used for the GDPCIR CMIP6 files, whose 0.25° cells are offset by half a cell from ERA5
    (centers at .125/.375 instead of .0/.25): each center lies between four ERA5 cells, so
    nearest-neighbor is a tie and bilinear gives their mean.
    """
    out = factor.interp(latitude=lat.values, longitude=lon.values, method="linear")
    out = out.rename({"latitude": "lat", "longitude": "lon"}).assign_coords(lat=lat, lon=lon)
    if bool(out.isnull().any()):
        raise ValueError("target grid extends beyond the factor grid")
    return out


def apply_monthly_factor(prcp: xr.DataArray, factor: xr.DataArray) -> xr.DataArray:
    """Multiply a precipitation series by the factor of each time step's calendar month.

    `prcp` and `factor` must share the spatial coordinates (e.g. both on the ERA5 grid).
    """
    corrected = prcp * factor.sel(month=prcp.time.dt.month).drop_vars("month")
    corrected.attrs = prcp.attrs
    return corrected.rename(prcp.name)

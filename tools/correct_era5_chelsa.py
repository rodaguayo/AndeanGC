"""Build the CHELSA V2.1 precipitation factors and the corrected ERA5 / CMIP6 precipitation.

Run once, before the pipeline, whenever the raw ERA5 precipitation or a `prcp_factor_*` key in
`config.yml` changes. Writes into `data_root`, beside the inputs, under the names in
`config.yml:inputs`:

    dirs.chelsa / inputs.prcp_factor   pr_factor(month, latitude, longitude)
    dirs.era5   / inputs.era5_prcp     daily ERA5 x factor of its month (read by nb06, nb07)
    dirs.cmip6  / <dirs.cmip6_raw names>  GDPCIR CMIP6 with the same factor applied to pr (nb07)

    python tools/correct_era5_chelsa.py              # build what is missing, check what exists
    python tools/correct_era5_chelsa.py --overwrite  # rebuild and replace everything

Whatif-Andes reads the same files (see `andeangc.precip_correction`), so a file that already
exists is not replaced unless asked: it is compared against the rebuilt one instead, and a
difference is reported, not silently written over. The CMIP6 files are corrected because GDPCIR
is bias-corrected to raw ERA5; leaving them raw would start the projections from a lower
precipitation than the corrected historical record. CHELSA downloads from
https://os.unil.cloud.switch.ch/chelsa02/chelsa/global/climatologies/pr/1981-2010/.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import xarray as xr

from andeangc import config as cfg
from andeangc import precip_correction as pc


def write(ds: xr.Dataset, path: Path, encoding: dict) -> None:
    """Write through a temporary file, so an interrupted run never leaves half a file."""
    tmp = path.with_suffix(".tmp")
    ds.to_netcdf(tmp, encoding=encoding)
    tmp.rename(path)


def main(overwrite: bool) -> None:
    era5_raw = cfg.data_dir('era5') / cfg.inputs['era5'].format(variable="prcp")
    factor_file = cfg.data_dir('chelsa') / cfg.inputs['prcp_factor']
    era5_file = cfg.data_dir('era5') / cfg.inputs['era5_prcp']
    raw = xr.open_dataset(era5_raw).prcp

    chelsa = [cfg.data_dir('chelsa') / cfg.inputs['chelsa_pr'].format(month=m) for m in range(1, 13)]
    factor = pc.chelsa_era5_factors(chelsa, raw,
                                    period=cfg.prcp_factor_period,
                                    cap=cfg.prcp_factor_cap,
                                    land=cfg.data_dir('dem') / cfg.inputs['dem_attributes'],
                                    floor_period=cfg.prcp_factor_floor_period)
    assert float(factor.max()) <= cfg.prcp_factor_cap + 1e-5, "cap violated"
    print("factor quantiles (0, 1, 50, 99, 100%):",
          factor.quantile([0, 0.01, 0.5, 0.99, 1]).round(2).values)

    if factor_file.exists() and not overwrite:
        stored = xr.open_dataset(factor_file).pr_factor
        diff = float(abs(stored - factor).max())
        print(f"{factor_file.name}: exists, max |stored - rebuilt| = {diff:.2e}")
        if diff > 1e-4:
            raise SystemExit("the stored factors differ from the rebuilt ones: check config.yml:prcp_factor_*, "
                             "or rerun with --overwrite to replace them (Whatif-Andes reads the same file)")
        factor = stored  # apply exactly what is on disk
    else:
        write(factor.to_dataset(), factor_file, {})
        print(f"{factor_file.name}: written")

    if era5_file.exists() and not overwrite:
        print(f"{era5_file.name}: exists, kept")
    else:
        corrected = pc.apply_monthly_factor(raw, factor).to_dataset()
        corrected.prcp.attrs["comment"] = factor.attrs["description"]
        # float32, not the raw packing (int32, 0.1 mm steps): that would round small corrected
        # daily values back down and break the annual floor
        write(corrected, era5_file, {"prcp": {"dtype": "float32", "zlib": True, "complevel": 4}})
        print(f"{era5_file.name}: written")

    # annual factor actually delivered over the floor period: never below 1
    period = slice(*cfg.prcp_factor_floor_period)
    ratio = xr.open_dataset(era5_file).prcp.sel(time=period).sum("time") / raw.sel(time=period).sum("time")
    print("delivered annual factor, min:", round(float(ratio.min()), 3))
    assert float(ratio.min()) >= 0.999, "annual floor violated"

    cmip6_raw, cmip6_cor = cfg.data_dir('cmip6_raw'), cfg.data_dir('cmip6')
    cmip6_cor.mkdir(exist_ok=True)
    for path in sorted(cmip6_raw.glob("*.nc")):
        out = cmip6_cor / path.name
        if out.exists() and not overwrite:
            continue
        with xr.open_dataset(path, chunks={"time": 3653}) as gcm:
            # GDPCIR cells are offset by half a cell from ERA5: the factor is interpolated bilinearly
            gcm = gcm.assign(pr=pc.apply_monthly_factor(gcm.pr, pc.factor_on_grid(factor, gcm.lat, gcm.lon)))
            gcm.attrs["pr_correction"] = factor.attrs["description"]
            # other variables keep their packing; pr as float32 (see the ERA5 file above)
            encoding = {v: {k: gcm[v].encoding[k] for k in ("dtype", "scale_factor", "_FillValue")
                            if k in gcm[v].encoding} | {"zlib": True, "complevel": 4}
                        for v in gcm.data_vars if v != "pr"}
            encoding["pr"] = {"dtype": "float32", "zlib": True, "complevel": 4}
            write(gcm, out, encoding)
        print(f"cmip6/{path.name}: written")
    print(f"{len(list(cmip6_cor.glob('*.nc')))} corrected CMIP6 files in {cmip6_cor}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--overwrite", action="store_true", help="rebuild and replace files that already exist")
    main(parser.parse_args().overwrite)

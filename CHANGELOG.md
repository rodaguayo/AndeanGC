# Changelog

---

## v1.1 — 2026-09-08

- **Changed** — historical ERA5 climate now runs 1960–2025.
- **Added** — `AndeanGC_signatures.csv`: the CAMELS hydrological signature set over the 1990–2019 reference period
- **Added** — `glacier_cover_RGI70` in `AndeanGC_metadata.csv`, beside `glacier_cover_RGI60`; RGI v6.0 still selects the basins.
- **Added** — `pet_mean_GLEAM` mean annual potential and `et_mean_GLEAM` actual evaporation (mm) over the 1990–2019 reference period, from GLEAM v4.3a.
- **Added** — `lai_max` and `lai_diff` in `AndeanGC_metadata.csv`: the annual
  maximum and the seasonal amplitude of the basin-mean leaf area index, from the GIMMS LAI4g v1.2
  monthly climatology (1982–2020).
- **Added** — Added testing for many functions
- **Breaking** — `glacier_area_RGI60` renamed `glacier_cover_RGI60`: it always held a percentage of basin area, not km².
- **Breaking** — published filenames no longer carry the period:
  `AndeanGC_data_1950_2024.csv` → `AndeanGC_data.csv`, etc...
- **Breaking** — `ev_mean_ERA5` renamed `pet_mean_ERA5`: it was always potential evaporation, and `et_mean_GLEAM` now sits beside it.
- **Breaking** — `aspect_mean` is replaced by `aspect_north` and `aspect_east` in
  `AndeanGC_metadata.csv`
- **Breaking** — new gauge_id format per source
- **Breaking** — the `dataset_version.yml`was removed. Future changes will be included in this file
- **Fixed** — Peruvian records were attached to the wrong gauge in v1.0 (nb01 assigned ids positionally); all 26 are now keyed by station name.
- **Unchanged** — streamflow period (1950–2024), 257 stations.
---

## v1.0 — 2026-05-28

Initial public release. DOI: [10.5281/zenodo.18035801](https://doi.org/10.5281/zenodo.18035801)

Daily streamflow 1950–2024 for 257 glacierized Andean catchments, from CAMELS-CL,
PMET-obs, SNIH and SENAMHI/ANDREA, with basin polygons, 38 attributes and ERA5 climate
series (1960–2024). See [data/v10/README_zenodo.md](data/v10/README_zenodo.md).

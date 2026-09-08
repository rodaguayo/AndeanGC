# Andean Glacierized Catchment (Andean-GC) dataset

A comprehensive streamflow dataset for glacierized basins across the Andes mountains (glacier area > 0.1%), integrating data from Chile, Peru, and Argentina. The dataset combines institutional streamflow records with basin characteristics including topographic, climatic, and land cover attributes, along with historical climate data for hydrological analysis and modeling. The final dataset is available on Zenodo: [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18035800.svg)](https://doi.org/10.5281/zenodo.18035800)

## Sources

Contains processed institutional streamflow datasets:

| Region | Subregion | Source/Platform | Reference/Website |
|--------|-----------|-----------------|-------------------|
| Chile | < 40° S | CAMELS-CL | [Link](https://doi.org/10.5194/hess-22-5817-2018) |
| Patagonia | > 40° S | PMET-obs | [Link](https://www.nature.com/articles/s41597-023-02828-2) |
| Argentina | > 40° S | SNIH | [Link](http://snih.hidricosargentina.gob.ar/) |
| Peru | - | SENAMHI / ANDREA | [Link](https://snirh.ana.gob.pe/ANDREA/Inicio.aspx) |

Additional data sources:
- **Glacier coverage**: RGI v6.0 and v7.0
- **Climate data**: ERA5 (1960-2025)
- **Evaporation**: GLEAM v4.3a (1980-2025)
- **Topography**: FABDEM (based on COPDEM)
- **Land cover**: CGLOPS-1 (2019)

## Workflow

The data processing pipeline consists of eight notebooks in the [`processing/`](processing/) folder, run in order:

- [`01_data_preprocessing.ipynb`](processing/01_data_preprocessing.ipynb): Cleans, standardizes and updates raw institutional streamflow data (SENAMHI, SNHI, CAMELS-CL, PMETobs)
- [`02_basins_delineation.ipynb`](processing/02_basins_delineation.ipynb): Delineates drainage basins from gauge coordinates using FABDEM and WhiteboxTools; converts basins to vector
- [`03_dataset_merging.ipynb`](processing/03_dataset_merging.ipynb): Merges standardized datasets and assembles the unified AndeanGC metadata, timeseries, and basin geometries
- [`04_dataset_filtering.ipynb`](processing/04_dataset_filtering.ipynb): Applies selection and quality filters (glacier coverage > 0.1%, data length, intervention keywords) and saves the cleaned dataset
- [`05_streamflow_qc.ipynb`](processing/05_streamflow_qc.ipynb): Performs automatic and visual/manual quality check on streamflow time series using `saqc`
- [`06_basins_attributes.ipynb`](processing/06_basins_attributes.ipynb): Extracts multiple basin attributes (topographic, climatic, glacier, land cover, dams, leaf area index)
- [`07_basins_climate.ipynb`](processing/07_basins_climate.ipynb): Processes historical climate time series from ERA5 reanalysis for selected basins
- [`08_hydro_signatures.ipynb`](processing/08_hydro_signatures.ipynb): Computes the CAMELS hydrological signature set per catchment from the QC'd streamflow and the ERA5 precipitation, over the same reference period as the climate attributes (`config.yml:period_ref_climate`)

Stage order matters: notebooks 03–06 read and overwrite the same three artifacts in place, so
re-running an earlier stage after a later one desynchronises the metadata from the timeseries.
`pixi run pipeline` executes all in order.

## Repository structure

```
├── data/                  # Data — NOT in git (OneDrive backup, Zenodo release)
│   ├── resources/         #   institutional streamflow data, shared by all versions
│   │   └── gauge_ids_peru.csv  # permanent gauge_id per SENAMHI station — never renumber
│   └── vXX/               #   one folder per dataset version (v10, v11, ...)
├── figures/               # Jupyter notebooks that produce the plots
├── processing/            # Jupyter notebooks (data processing pipeline)
├── andeangc/              # Utility functions (installed package)
├── pixi.toml              # Pixi project manifest (conda-forge + pip)
├── pixi.lock              # Pixi lockfile (auto-generated)
├── pyproject.toml         # Project metadata and pip dependencies
├── config.yml             # Paths, periods and thresholds for the whole pipeline
├── CITATION.cff           # Machine-readable citation metadata
├── CHANGELOG.md           # What changed between published dataset versions
├── tests/                 # Unit tests for the helper modules
├── .gitattributes         # nbstripout filter: notebooks commit without outputs
└── .github/workflows/     # CI: lint, tests, notebook check
```

## Getting started

```bash
pixi install
pixi shell
```

## Citation

If you use this dataset, please cite:

```
Aguayo, R., Zekollari, H., van Tiel, M., Bolibar, J., Van Tricht, L., Ayala Ramos, A. I., & Ultee, L. (2026). Andean Glacierized Catchment (Andean-GC) dataset (Version v1.1) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.18035800
```

Machine-readable metadata is in [CITATION.cff](CITATION.cff); GitHub renders it as the "Cite this repository" button and can export BibTeX or APA from it.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Contact

Rodrigo Aguayo — [Personal website](https://rodaguayo.github.io/)

## Acknowledgments

- Data providers: DGA Chile, SNIH Argentina, SENAMHI Peru
- Funding: FWO

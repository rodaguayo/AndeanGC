# Andean Glacierized Catchment (Andean-GC) dataset

A comprehensive streamflow dataset for glacierized basins across the Andes mountains (glacier area > 0.1%), integrating data from Chile, Peru, and Argentina. The dataset combines institutional streamflow records with basin characteristics including topographic, climatic, and land cover attributes, along with historical climate data for hydrological analysis and modeling. The final dataset is available on Zenodo: [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18035801.svg)](https://doi.org/10.5281/zenodo.18035801)

## Sources

Contains processed institutional streamflow datasets:

| Region | Subregion | Source/Platform | Reference/Website |
|--------|-----------|-----------------|-------------------|
| Chile | < 40° S | CAMELS-CL | [Link](https://doi.org/10.5194/hess-22-5817-2018) |
| Patagonia | > 40° S | PMET-obs | [Link](https://www.nature.com/articles/s41597-023-02828-2) |
| Argentina | > 40° S | SNIH | [Link](http://snih.hidricosargentina.gob.ar/) |
| Peru | - | SENAMHI / ANDREA | [Link](https://snirh.ana.gob.pe/ANDREA/Inicio.aspx) |

Additional data sources:
- **Glacier coverage**: RGI v6.0
- **Climate data**: ERA5 (1960-2024)
- **Topography**: FABDEM (based on COPDEM)
- **Land cover**: CGLOPS-1 (2019)

## Workflow

The data processing pipeline consists of eight notebooks in the [`processing/`](processing/) folder:

- [`01_data_preprocessing.ipynb`](processing/01_data_preprocessing.ipynb): Cleans, standardizes and updates raw institutional streamflow data (SENAMHI, SNHI, CAMELS-CL, PMETobs)
- [`02_basins_delineation.ipynb`](processing/02_basins_delineation.ipynb): Delineates drainage basins from gauge coordinates using FABDEM and WhiteboxTools; converts basins to vector
- [`03_dataset_merging.ipynb`](processing/03_dataset_merging.ipynb): Merges standardized datasets and assembles the unified AndeanGC metadata, timeseries, and basin geometries
- [`04_dataset_filtering.ipynb`](processing/04_dataset_filtering.ipynb): Applies selection and quality filters (glacier coverage > 0.1%, data length, intervention keywords) and saves the cleaned dataset
- [`05_streamflow_qc.ipynb`](processing/05_streamflow_qc.ipynb): Performs automatic and visual/manual quality check on streamflow time series using `saqc`
- [`06_basins_attributes.ipynb`](processing/06_basins_attributes.ipynb): Extracts multiple basin attributes (topographic, climatic, glacier, land cover, dams)
- [`07_basins_climate.ipynb`](processing/07_basins_climate.ipynb): Processes historical climate time series from ERA5 reanalysis for selected basins

## Repository structure

```
├── data/                  # Data — NOT in git (OneDrive backup, Zenodo release)
│   ├── resources/         #   institutional streamflow data, shared by all versions
│   └── v10/               #   one folder per dataset version (v10, v11, ...)
│       ├── AndeanGC_data_1950_2024.csv     # published dataset
│       ├── AndeanGC_data_1950_2024_qc.csv
│       ├── AndeanGC_metadata.csv
│       ├── AndeanGC_shape.gpkg
│       ├── climate/       #     historical/ (ERA5) and future/ (CMIP6) time series
│       ├── figures/       #     generated plots
│       ├── dataset_version.yml  # manifest for this version
│       └── README_zenodo.md     # Zenodo record for this version
├── figures/               # Jupyter notebooks that produce the plots
├── processing/            # Jupyter notebooks (data processing pipeline)
├── andeangc/              # Utility functions (installed package)
│   ├── config.py          #   Resolve config.yml keys and data paths
│   ├── data_homogenize.py #   Parse raw SENAMHI Excel files
│   ├── data_update.py     #   Extend datasets with recent records
│   ├── basin_delineation.py #  WhiteboxTools delineation pipeline (nb02)
│   ├── basin_attributes.py #  Topographic, glacier, land cover and dam attributes (nb06)
│   └── polygon_extract.py #   Zonal raster statistics and time series extraction
├── pixi.toml              # Pixi project manifest (conda-forge + pip)
├── pixi.lock              # Pixi lockfile (auto-generated)
├── pyproject.toml         # Project metadata and pip dependencies
```

Historical data includes ERA5 (1960–2024). CMIP6 climate projections are available upon request. The `data/` tree is deliberately outside git: it is published to Zenodo, while git tracks only the code that produces it.


## Getting started

```bash
pixi install
pixi shell
```

## Citation

If you use this dataset, please cite:

```
Aguayo, R. Andean Glacierized Catchment (Andean-GC) dataset. https://doi.org/10.5281/zenodo.18035801 (2026).
```

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Contact

Rodrigo Aguayo — [Personal website](https://rodaguayo.github.io/)

## Acknowledgments

- Data providers: DGA Chile, SNIH Argentina, SENAMHI Peru
- Funding: FWO

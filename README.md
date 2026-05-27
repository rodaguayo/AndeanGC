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

- [`00_prepare_glacier_data.ipynb`](processing/00_prepare_glacier_data.ipynb): Prepares and processes glacier datasets (RGI, dhdt, volume rasters — reprojection, merging, resampling)
- [`01_data_preprocessing.ipynb`](processing/01_data_preprocessing.ipynb): Cleans, standardizes and updates raw institutional streamflow data (SENAMHI, SNHI, CAMELS-CL, PMETobs)
- [`02_basins_delineation.ipynb`](processing/02_basins_delineation.ipynb): Delineates drainage basins from gauge coordinates using FABDEM and WhiteboxTools; converts basins to vector
- [`03_dataset_merging.ipynb`](processing/03_dataset_merging.ipynb): Merges standardized datasets and assembles the unified AndeanGC metadata, timeseries, and basin geometries
- [`04_dataset_filtering.ipynb`](processing/04_dataset_filtering.ipynb): Applies selection and quality filters (glacier coverage > 0.1%, data length, intervention keywords) and saves the cleaned dataset
- [`05_streamflow_qc.ipynb`](processing/05_streamflow_qc.ipynb): Performs automatic and visual/manual quality check on streamflow time series using `saqc`
- [`06_basins_attributes.ipynb`](processing/06_basins_attributes.ipynb): Extracts multiple basin attributes (topographic, climatic, glacier, land cover, dams)
- [`07_basins_climate.ipynb`](processing/07_basins_climate.ipynb): Processes historical climate time series from ERA5 reanalysis for selected basins

## Repository structure

```
├── climate/               # Historical climate time series (ERA5)
│   └── historical/        #   AndeanGC_*_ERA5_1960_2024.parquet
├── data/                  # Raw institutional streamflow data
│   ├── CAMELS_CL/         #   Chile (DGA)
│   ├── PMET_OBS/          #   Patagonia
│   ├── SENAMHI_PERU/      #   Peru (raw .xlsx + processed)
│   └── SNHI_ARG/          #   Argentina (raw .xlsx + processed)
├── dataset/               # Final processed dataset (see zenodo repository)
├── figures/               # Generated plots and visualizations
├── processing/            # Jupyter notebooks (data processing pipeline)
├── utils/                 # Utility functions
│   ├── data_homogenize.py #   Parse raw SENAMHI Excel files
│   ├── data_update.py     #   Extend datasets with recent records
│   └── polygon_extract.py #   Zonal raster statistics and time series extraction
├── environment.yml        # Conda environment (conda-forge)
├── pyproject.toml         # Project metadata and pip dependencies
└── requirements.txt       # Minimal pip dependencies
```

Historical data includes ERA5 (1960–2024). CMIP6 climate projections are available upon request.

## Getting started

```bash
# Conda (recommended)
conda env create -f environment.yml
conda activate andeangc

# or pip
pip install -e .
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

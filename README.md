# Andean Glacierized Catchment (Andes-GC) dataset

A comprehensive streamflow dataset for glacierized basins across the Andes mountains (glacier area > 0.1%), integrating data from Chile, Peru, and Argentina. The dataset combines institutional streamflow records with basin characteristics including topographic, climatic, and land cover attributes, along with historical and future climate projections for hydrological analysis and modeling. The final dataset is available on Zenodo: [![DOI](https://zenodo.org/badge/DOI/[ADD_ZENODO_DOI].svg)](https://doi.org/[ADD_ZENODO_DOI])


## Sources

Contains processed institutional streamflow datasets:

| Country | Region | Source | Reference |
|---------|--------|--------|-----------|
| Chile | >40° S | CAMELS-CL | add link |
| Patagonia | <40° S | PMET-obs | add link |
| Argentina | >40° S | Sistema Nacional de Información Hídrica | add link |
| Peru | - | Andrea Platform | add link |

Additional data sources:
- **Glacier coverage**: Randolph Glacier Inventory (RGI) v7.0
- **Climate data**: ERA5 reanalysis (1950-present)
- **Climate projections**: CMIP6 models
- **Topography**: SRTM/ASTER DEM
- **Land cover**: [specify source]

## Workflow

The following Jupyter notebooks are included in the `processing/` folder to facilitate the data processing workflow:

The data processing pipeline consists of seven notebooks in the [`processing/`](processing/) folder:

1.  [`00_prepare_glacier_data.ipynb`](processing/00_prepare_glacier_data.ipynb): Prepares and processes glacier coverage data (RGI) for basin analysis
2.  [`01_data_preprocessing.ipynb`](processing/01_data_preprocessing.ipynb): Cleans and standardizes raw institutional streamflow data from multiple sources
3.  [`02_basins_delineation.ipynb`](processing/02_basins_delineation.ipynb): Delineates drainage basins from gauge coordinates using digital elevation models
4.  [`03_data_aggregation_filtering.ipynb`](processing/03_data_aggregation_filtering.ipynb): Merges datasets and filters basins based on criteria (glacier coverage > 0.1%)
5.  [`04_streaflow_quality_check.ipynb`](processing/04_streaflow_quality_check.ipynb): Performs quality control checks on streamflow time series data
6.  [`05_basins_attributes.ipynb`](processing/05_basins_attributes.ipynb): Extracts basin characteristics including topography, climate variables from ERA5, and land cover
7.  [`06_basins_climate.ipynb`](processing/06_basins_climate.ipynb): Processes climate time series from ERA5 reanalysis and CMIP6 projections for selected basins


## Folder description

```
├── climate/               # Climate data (ERA5, CMIP6; see zenodo repo)
├── data/                  # Raw institutional streamflow data
├── dataset/               # Final processed dataset (see zenodo repo)
├── processing/            # Jupyter notebooks for data processing workflow
├── utils/                 # Utility functions and helper scripts
└── figures/               # Generated plots and visualizations (not tracked)
```

### Citation

If you use this dataset, please cite:
```
[Add citation information]
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contact

Rodrigo Aguayo - [add contact information or link]

## Acknowledgments

- Data providers: DGA Chile, SNIH Argentina, SENAMHI Peru
- Funding sources: [if applicable]
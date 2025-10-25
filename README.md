# AndeanStreamflow Dataset

A comprehensive streamflow dataset for glacierized basins across the Andes mountains, integrating data from Chile, Peru, and Argentina. The dataset combines institutional streamflow records with basin characteristics including topographic, climatic, and land cover attributes, along with historical and future climate projections for hydrological analysis and modeling.



# Workflow

1.  **`Data_preprocessing.ipynb`**: Cleans and standardizes raw institutional streamflow data.
2.  **`Basins_delineation.ipynb`**: Delineates drainage basins from gauge coordinates using digital elevation models.
3.  **`Data_aggregation_filtering.ipynb`**: Merges datasets and filters basins based on criteria like glacier coverage.
4.  **`Basins_attributes.ipynb`**: Extracts key basin characteristics, including topography (e.g., slope, elevation), climate variables from ERA5, and land cover data.
5.  **`Basins_climate.ipynb`**: Processes and analyzes climate time series from ERA5 reanalysis and CMIP6 climate model outputs for the selected basins.

# Folder description

## data/

Contains processed institutional streamflow datasets:

* **CAMELS\_CL\_v2022/**: Chilean streamflow data from CAMELS-CL dataset
* **PMET\_OBS\_v11/**: PMETobs v11 streamflow observations
* **SENAMHI\_PERU/**: Peruvian streamflow data from SENAMHI
* **SNHI\_ARG/**: Argentine streamflow data from SNHI

## dataset/

Final aggregated datasets:

* **GGC\_Andes\_data\_1950\_2024.csv**: Combined streamflow time series for all basins
* **GGC\_Andes\_metadata.csv**: Basin metadata including coordinates, attributes, and institutional information
* **GGC\_Andes\_shape.gpkg**: Basin geometries and spatial attributes

## climate/

Climate data for basins:

* **historical/**: Historical climate time series
* **future/**: Future climate projections from CMIP6 models

## GIS/

Geospatial data files:

* **basins\_\*.gpkg**: Basin polygon shapefiles for each institution (CAMELS-CL, PMETobs, SENAMHI, SNHI)
* **stream\_gauges\_\*.gpkg**: Stream gauge point locations for SENAMHI and SNHI
* **basins\_temp/**: Temporary basin delineation files

## processing/

Jupyter notebooks for data processing workflow:

* **Data\_preprocessing.ipynb**: Clean and standardize raw institutional data
* **Basins\_delineation.ipynb**: Delineate drainage basins from gauge coordinates
* **Data\_aggregation\_filtering.ipynb**: Merge datasets and filter basins by glacier coverage
* **Basins\_attributes.ipynb**: Extract basin characteristics (topography, climate, land cover)
* **Basins\_climate.ipynb**: Process climate time series from ERA5 and CMIP6

## utils/

Utility functions and helper scripts:

## figures/

Generated plots and visualizations:


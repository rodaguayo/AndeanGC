import xagg as xa # faster for large netcdf files
from exactextract import exact_extract # faster for large rasters 
import xarray as xr

xa.set_options(silent = True)

def extract_attributes(raster, shapefile, attribute_name, fun="mean"):
    
    if isinstance(raster, str):
        raster = xr.open_dataset(raster)

    if raster.dims[0] == "lat" or raster.dims[0] == "lon":
        raster = raster.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=True)

    ds = exact_extract(raster.load(), shapefile, fun, include_cols=["gauge_id"], 
                       output="pandas", progress=False)
    ds = ds.set_index("gauge_id")
    ds.rename(columns={fun: attribute_name}, inplace=True)
    shape = shapefile.join(ds[attribute_name], on="gauge_id")

    return shape

xa.set_options(impl='for_loop')
def extract_timeseries(raster, shapefile):
    
    weightmap = xa.pixel_overlaps(raster, shapefile, impl='for_loop', silent=True)
    ds = xa.aggregate(raster, weightmap, impl = "numba", silent = True)
    ds = ds.to_dataframe()[raster.name].unstack('poly_idx')
    ds.columns = shapefile.gauge_id
    ds.columns.name = None
    ds = ds.round(3).astype("float32")
    return ds


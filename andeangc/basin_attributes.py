"""Basin attributes from external rasters and vectors (notebook 06).

Each function takes the basin GeoDataFrame and returns it with new columns
attached, so they compose: ``shape = topographic_attributes(shape)``. The
climate attributes are deliberately absent — their definitions (precipitation
concentration index, snow fraction, high/low precipitation frequency) are the
substance of that step and stay visible in the notebook, which builds them on
top of `era5_reference_stack` and `polygon_extract.extract_attributes`.

Rasters are read through `open_raster`, which clips to the basins' bounding box
first: the sources are Andes-wide (the 270 m DEM, the global land cover) and
reading them whole is what makes this notebook slow.
"""

from collections.abc import Sequence
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray as rio
import xarray as xr
import xrspatial as xrs
from exactextract import exact_extract

from andeangc import config as cfg
from andeangc import polygon_extract

# CGLOPS-1 / PROBA-V land cover class codes, mapped to the output column names.
LAND_COVER_CLASSES = {"forest_cover": 10,
                      "shrubs_veg_cover": 20,
                      "herbaceous_veg_cover": 30,
                      "cropland_cover": 40,
                      "urban_cover": 50,
                      "sparse_veg_cover": 60,
                      "water_cover": 80}

# Codes in this closed interval are the detailed forest classes; they are
# collapsed onto LAND_COVER_CLASSES["forest_cover"] before extraction.
LAND_COVER_FOREST_RANGE = (100, 200)


def clip_to(raster: xr.DataArray, shape: gpd.GeoDataFrame) -> xr.DataArray:
    """Clip a raster to the bounding box of the basins.

    `total_bounds` is (minx, miny, maxx, maxy) while the rasters are stored
    north-up, hence the flipped y slice.
    """
    minx, miny, maxx, maxy = shape.total_bounds
    return raster.sel(x=slice(minx, maxx), y=slice(maxy, miny))


def open_raster(path: str | Path, shape: gpd.GeoDataFrame | None = None, band: int = 1) -> xr.DataArray:
    """Open a single-band raster, dropping the band dimension and clipping."""
    raster = rio.open_rasterio(path).sel(band=band, drop=True)
    return clip_to(raster, shape) if shape is not None else raster


def geometry_attributes(shape: gpd.GeoDataFrame, epsg_utm: int = 32719) -> gpd.GeoDataFrame:
    """Centroid, perimeter and Gravelius compactness index.

    Measured on the projected geometry; the centroid is reported back in
    lat/lon. `basin_area` is expected to be present already, in km2.
    """
    projected = shape.to_crs(epsg_utm)  # UTM 19S, the Andes

    shape = shape.copy()
    shape["basin_cenlat"] = projected.centroid.to_crs(4326).y
    shape["basin_cenlon"] = projected.centroid.to_crs(4326).x
    shape["total_perim"] = projected.geometry.length / 1e3  # from m to km
    shape["gc_index"] = shape.total_perim / (2 * (np.sqrt(np.pi * shape.basin_area)))
    return shape


def topographic_attributes(shape: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Elevation (mean, median, std), slope and aspect, from the Andes-wide DEM.

    Slope is computed in UTM — it is meaningless in degrees — and reprojected
    back; aspect is direction only, so it stays in lat/lon.
    """
    dem = xr.open_dataset(cfg.data_dir('dem') / cfg.inputs['dem_attributes']).band_data.sel(band=1, drop=True)
    dem = clip_to(dem, shape)
    dem = dem.fillna(0)  # NAs to sea level (= 0)

    slope = xrs.slope(dem.rio.reproject("EPSG:32719"))  # UTM 19S, the Andes
    slope = slope.rio.reproject("EPSG:4326")
    aspect = xrs.aspect(dem)

    shape = polygon_extract.extract_attributes(dem, shape, {"elev_mean": "mean",
                                                            "elev_median": "median",
                                                            "elev_std": "stdev"})
    shape = polygon_extract.extract_attributes(slope, shape, "slope_mean")
    shape = polygon_extract.extract_attributes(aspect, shape, "aspect_mean")
    return shape


def era5_reference_stack(period: Sequence[str] | None = None) -> xr.Dataset:
    """The ERA5 variables over the reference period, with `tas` added.

    Left lazy and undisturbed otherwise: the notebook's climate cell does the
    aggregating, since that is where the attribute definitions live.

    The filenames come from `config.yml:inputs`, not from `period_climate`:
    the archive is stamped with the span it was downloaded with, which runs
    past the end of the published period.
    """
    period = period or cfg.period_ref_climate
    pattern = cfg.inputs['era5'].format(variable="*")

    stack = xr.open_mfdataset(str(cfg.data_dir('era5') / pattern))
    stack = stack.sel(time=slice(period[0], period[1]))
    stack['tas'] = (stack.tasmax + stack['tasmin']) / 2
    return stack


def glacier_attributes(shape: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Elevation change rate (m/yr) and ice volume (km3) per basin.

    dhdt is an average over the basin; the volumes are sums, so they are totals
    for the glaciers inside it.
    """
    outputs = cfg.outputs

    dhdt = open_raster(cfg.data_dir('glacier_dhdt') / outputs['glacier_dhdt'], shape)  # in m/yr
    shape = polygon_extract.extract_attributes(dhdt, shape, "glacier_dhdt", fun="mean")

    for attribute, output in (("glacier_volume_M22", 'glacier_volume_millan'),
                              ("glacier_volume_F19", 'glacier_volume_farinotti')):
        volume = open_raster(cfg.data_dir('glacier_thickness') / outputs[output], shape)  # in km3
        shape = polygon_extract.extract_attributes(volume, shape, attribute, fun="sum")

    return shape


def land_cover_attributes(shape: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Percentage of each CGLOPS-1 class per basin, named by LAND_COVER_CLASSES.

    The detailed forest classes are collapsed onto the single forest code
    first. Unlike the other attributes this one returns the basins indexed by
    gauge_id, because the fractions arrive that way.

    A class absent from every basin in the run gets a column of zeros rather
    than raising: `exact_extract` only reports the codes it actually saw.
    """
    classes = LAND_COVER_CLASSES
    forest_range = LAND_COVER_FOREST_RANGE

    land_cover = open_raster(cfg.data_dir('land_cover') / cfg.inputs['land_cover'], shape)
    land_cover = land_cover.where(~((land_cover >= forest_range[0]) & (land_cover <= forest_range[1])),
                                  classes['forest_cover'])

    fractions = exact_extract(land_cover, shape, ["unique", "frac"], progress=False,
                              output="pandas", include_cols=["gauge_id"])
    # strict: exact_extract returns one fraction per class code, so a length
    # mismatch would mean silently dropping a land cover class.
    fractions = fractions.apply(lambda row: pd.Series(dict(zip(row['unique'], row['frac'], strict=True))), axis=1)
    fractions = fractions.set_index(shape.gauge_id).fillna(0) * 100
    fractions = fractions.reindex(columns=list(classes.values()), fill_value=0)

    shape = shape.set_index("gauge_id")
    for column, code in classes.items():
        shape[column] = fractions[code]
    return shape


def dam_attributes(shape: gpd.GeoDataFrame, capacity_threshold: float = 100) -> gpd.GeoDataFrame:
    """Number of large dams inside each basin.

    Only dams above `capacity_threshold` count, in the units of GDAT's `Capac`
    column.
    """
    dams = gpd.read_file(cfg.data_dir('dams') / cfg.inputs['dams'])
    dams = dams[dams.Capac > capacity_threshold]

    counts = gpd.sjoin(dams, shape.reset_index(), how='inner', predicate='within')
    counts = counts.groupby('gauge_id').size()

    shape = shape.join(counts.rename("dams_count"))
    shape["dams_count"] = shape["dams_count"].fillna(0)
    return shape

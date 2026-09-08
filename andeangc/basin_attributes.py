"""Basin attributes from external rasters and vectors (notebook 06).

Each function takes the basin GeoDataFrame and returns it with new columns
attached, so they compose: ``shape = topographic_attributes(shape)``.
`glacier_cover` is the exception on both counts — it is called from notebook 04,
where the glacier fraction is the filter that selects the basins, and it returns
a bare Series because that notebook computes one per RGI version and names the
columns itself. The
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


def clip_to(raster: xr.DataArray | xr.Dataset, shape: gpd.GeoDataFrame) -> xr.DataArray | xr.Dataset:
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

    Slope and aspect are both computed in UTM and reprojected back: in degrees
    the cell is not square away from the equator, so the two gradients are scaled
    by different real distances — which inflates slope and tilts the direction
    aspect points (xrspatial warns about exactly this).

    Aspect is published as its two unit-vector components rather than as a mean
    bearing, because bearings are circular: 359° and 1° are neighbours, and their
    arithmetic mean is 180°, the exact opposite direction. `aspect_north` is the
    basin mean of cos(aspect) and `aspect_east` the mean of sin(aspect), each in
    [-1, 1] — +1 fully north- (east-) facing, -1 fully south- (west-) facing, and
    ~0 either a basin with no preferred exposure or one facing across that axis.
    Both are usable as-is in a regression, which a bearing is not, and the mean
    bearing is recoverable as ``degrees(atan2(aspect_east, aspect_north)) % 360``.
    Flat cells, which xrspatial marks -1, have no direction and are dropped rather
    than counted as due north.
    """
    dem = xr.open_dataset(cfg.data_dir('dem') / cfg.inputs['dem_attributes']).band_data.sel(band=1, drop=True)
    dem = clip_to(dem, shape)
    dem = dem.fillna(0)  # NAs to sea level (= 0)

    dem_utm = dem.rio.reproject("EPSG:32719")  # UTM 19S, the Andes
    slope = xrs.slope(dem_utm).rio.reproject("EPSG:4326")

    aspect = np.deg2rad(xrs.aspect(dem_utm).where(lambda a: a >= 0))
    northness = np.cos(aspect).rio.write_nodata(np.nan).rio.reproject("EPSG:4326")
    eastness = np.sin(aspect).rio.write_nodata(np.nan).rio.reproject("EPSG:4326")

    shape = polygon_extract.extract_attributes(dem, shape, {"elev_mean": "mean",
                                                            "elev_median": "median",
                                                            "elev_std": "stdev"})
    shape = polygon_extract.extract_attributes(slope, shape, "slope_mean")
    shape = polygon_extract.extract_attributes(northness, shape, "aspect_north")
    shape = polygon_extract.extract_attributes(eastness, shape, "aspect_east")
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


def gleam_reference_stack(shape: gpd.GeoDataFrame | None = None,
                          period: Sequence[str] | None = None) -> xr.Dataset:
    """GLEAM actual (`E`) and potential (`Ep`) evaporation over the reference period.

    Left lazy, like `era5_reference_stack`, and for the same reason: what the
    two evaporation attributes are is the notebook's business, not this
    function's. The archive stores one file per variable and year, already
    aggregated to annual totals in mm, so the stack comes back with one step per
    year — the notebook averages over it where the ERA5 cell has to resample
    first.

    Two things differ from ERA5 and are handled here rather than in the
    notebook. GLEAM is global at 0.1 degrees while the ERA5 archive is already
    cut to the Andes, so `shape` clips the stack to the basins' bounding box on
    open; skipping that reads 46 global years twice over. And it names its axes
    lat/lon, which is renamed to y/x so that `clip_to` and `exact_extract` both
    find the spatial dimensions.
    """
    period = period or cfg.period_ref_climate
    pattern = cfg.inputs['gleam'].format(variable="*", year="*")

    stack = xr.open_mfdataset(str(cfg.data_dir('gleam') / pattern))
    stack = stack.sel(time=slice(period[0], period[1])).rename(lat="y", lon="x")
    return clip_to(stack, shape) if shape is not None else stack


def glacier_cover(shape: gpd.GeoDataFrame, rgi_version: str, epsg_utm: int = 32719) -> pd.Series:
    """Glacier cover per basin, as a percentage of `basin_area`, from the RGI outlines.
    
    A basin that touches no outline gets 0, not NaN: an ice-free basin has a
    glacier cover, and it is zero.
    """
    outlines = pd.concat([gpd.read_file(cfg.data_dir('glacier_outlines') / f"{rgi_version}_{region}.shp")
                          for region in cfg.rgi_regions])
    ice = outlines.union_all()

    cover = pd.Series(0.0, index=shape.index)
    touching = shape[shape.intersects(ice)]
    glacier_area = touching.intersection(ice).to_crs(epsg=epsg_utm).area / 1e6  # UTM 19S, the Andes
    cover.loc[touching.index] = glacier_area * 100 / touching.basin_area
    return cover.fillna(0)


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

    # Assigned rather than joined, so a re-run over basins that already carry the column
    # overwrites it instead of raising on the overlap (see `extract_attributes`).
    shape = shape.copy()
    shape["dams_count"] = counts.reindex(shape.index).fillna(0)
    return shape


def lai_attributes(shape: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Leaf area index seasonality per basin: the annual maximum and its amplitude.

    The source is the monthly LAI climatology, one band per month, so the two
    CAMELS vegetation attributes (Addor et al. 2017) are a max and a range over
    the twelve basin means: `lai_max` is the largest, `lai_diff` the largest
    minus the smallest.

    Unretrieved pixels count as zero leaf area rather than as missing data.
    GIMMS LAI4g reports nothing over barren surfaces — the Atacama, and the bare
    rock and ice above the vegetation limit — but inside a catchment those are
    real surface with no leaves on it, so excluding them would report the mean
    LAI of the vegetated fraction instead of the basin mean, and would leave the
    driest basins with no value at all. The fill is safe because the masking is
    permanent, never seasonal: in the Andes every pixel is retrieved in all
    twelve months or in none, so a filled pixel cannot manufacture an amplitude
    in `lai_diff`. Fully barren basins (56 of the 726 in v11) come out at zero.
    """
    lai = xr.open_dataset(cfg.data_dir('lai') / cfg.inputs['lai_climatology']).lai
    lai = clip_to(lai.rename(lat="y", lon="x"), shape)
    lai = lai.fillna(0)  # unretrieved surface carries no leaves

    # One column per month, in the row order of `shape` — hence the positional
    # assignment below, which holds whether the caller indexes by gauge_id
    # (as `land_cover_attributes` leaves it) or by position.
    months = exact_extract(lai.load(), shape, ["mean"], progress=False, output="pandas")

    shape = shape.copy()
    shape["lai_max"] = months.max(axis=1).to_numpy()
    shape["lai_diff"] = (months.max(axis=1) - months.min(axis=1)).to_numpy()
    return shape

"""Basin delineation from gauge coordinates (notebook 02).

The four stages, in order: `write_pour_points` turns gauge metadata into a
shapefile, `route_flow` fills and routes a region's DEM, `delineate` snaps the
pour points and unnests the basins, and `basins_to_gdf` vectorises them.
Notebook 02 drives them region by region and writes the result.

Two identifiers name each region and they are not interchangeable: `source` is
the institution (SENAMHI, SNHI), which names the gauge files and the delineated
output, while `region` is the DEM tag (PERU, ARG). Together they name the
resources folder, e.g. ``SENAMHI_PERU/``. Notebook 02 holds the pairs.

Every stage returns the paths it wrote, so the notebook can hand that exact
list to `remove_files` instead of globbing the shared DEM directory.
"""

import warnings
from collections.abc import Iterable, Sequence
from glob import glob
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rioxarray as rxr
import whitebox
from geocube.vector import vectorize

from andeangc import config as cfg


def whitebox_tools(verbose: bool = False) -> whitebox.WhiteboxTools:
    """A WhiteboxTools instance configured as this pipeline expects."""
    wbt = whitebox.WhiteboxTools()
    wbt.set_compress_rasters(True)
    wbt.set_verbose_mode(verbose)
    return wbt


def temp_dir() -> Path:
    """Scratch directory for the intermediate rasters and shapefiles."""
    path = cfg.ROOT / "temp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_pour_points(source: str, region: str, resources: str | Path | None = None,
                      epsg: int = 4326) -> Path:
    """Write one region's gauge coordinates as a pour-point shapefile.

    Only gauges that appear in both the daily timeseries and the metadata are
    kept — a gauge with no coordinates cannot be delineated, and SNHI currently
    has 110 timeseries against 75 metadata rows. The gauge ids travel along as
    the shapefile's `index` field, which is how the delineated basins get their
    ids back in `basins_to_gdf`.
    """
    resources = Path(resources) if resources else cfg.RESOURCES

    data_dir = resources / f"{source}_{region}"
    q_data = pd.read_csv(data_dir / f"{source}_data.csv", index_col=0, parse_dates=["date"])
    metadata = pd.read_csv(data_dir / f"{source}_metadata.csv", encoding="latin", index_col=0)

    gauges = q_data.columns.intersection(metadata.index)
    if len(gauges) < len(q_data.columns):
        warnings.warn(f"{source}: {len(q_data.columns) - len(gauges)} of {len(q_data.columns)} gauges "
                      f"are missing from {source}_metadata.csv and cannot be delineated",
                      stacklevel=2)  # point at the caller, not at this line
    metadata = metadata.loc[gauges]

    points = gpd.GeoSeries(gpd.points_from_xy(x=metadata.gauge_lon, y=metadata.gauge_lat),
                           index=metadata.index, crs=f"EPSG:{epsg}")
    output = temp_dir() / f"stream_gauges_{source}.shp"
    points.to_file(output)
    return output


def route_flow(region: str, wbt: whitebox.WhiteboxTools | None = None,
               dem_dir: str | Path | None = None, resolution: int | None = None,
               stream_threshold: float | None = None) -> dict[str, Path]:
    """Fill depressions, route flow and extract the stream network.

    The four rasters are written beside the input DEM, in the shared DEM
    directory, and returned keyed by role. `stream_threshold` is a minimum
    contributing area, not a number of cells.
    """
    wbt = wbt or whitebox_tools()
    dem_dir = Path(dem_dir) if dem_dir else cfg.data_dir('dem')
    resolution = resolution or cfg.dem_resolution
    stream_threshold = cfg.stream_threshold if stream_threshold is None else stream_threshold

    dem = dem_dir / f"DEM_{region}_{resolution}m.tif"
    rasters = {role: dem_dir / f"DEM_{region}_{resolution}m_{role}.tif"
               for role in ("filled", "flow_dir", "flow_acc", "streams")}

    wbt.flow_accumulation_full_workflow(
        dem=str(dem),
        out_dem=str(rasters["filled"]),
        out_pntr=str(rasters["flow_dir"]),
        out_accum=str(rasters["flow_acc"]),
        )

    wbt.extract_streams(
        flow_accum=str(rasters["flow_acc"]),
        output=str(rasters["streams"]),
        threshold=stream_threshold,
        zero_background=True,
        )

    return rasters


def delineate(source: str, routing: dict[str, Path], pour_points: str | Path | None = None,
              wbt: whitebox.WhiteboxTools | None = None,
              snap_dist: float | None = None) -> tuple[Path, list[Path]]:
    """Snap the pour points to the stream network and unnest the basins.

    Returns (snapped_points, basin_rasters); `unnest_basins` writes one raster
    per nesting level, so the rasters are collected by glob afterwards.
    """
    wbt = wbt or whitebox_tools()
    snap_dist = snap_dist or cfg.snap_dist
    pour_points = Path(pour_points) if pour_points else temp_dir() / f"stream_gauges_{source}.shp"
    snapped = temp_dir() / f"stream_gauges_{source}_snap.shp"

    wbt.jenson_snap_pour_points(
        streams=str(routing["streams"]),
        pour_pts=str(pour_points),
        output=str(snapped),
        snap_dist=snap_dist,
        )

    wbt.unnest_basins(
        d8_pntr=str(routing["flow_dir"]),
        pour_pts=str(snapped),
        output=str(temp_dir() / f"basins_{source}.tif"),
        )

    basin_rasters = sorted(Path(p) for p in glob(str(temp_dir() / f"basins_{source}*.tif")))
    return snapped, basin_rasters


def basins_to_gdf(basin_rasters: Sequence[str | Path], snapped_points: str | Path) -> gpd.GeoDataFrame:
    """Vectorise the unnested basin rasters into one polygon per gauge."""
    polygons, crs = [], None
    for raster in basin_rasters:
        basin = rxr.open_rasterio(raster)
        basin.name = "id"  # assign a name to avoid warning
        polygons.append(vectorize(basin))
        crs = basin.rio.crs

    gdf = gpd.GeoDataFrame(pd.concat(polygons, ignore_index=True), crs=crs)
    gdf = gdf.dissolve(by="id").reset_index()
    gdf["gauge_id"] = gpd.read_file(snapped_points).set_index("index").index
    return gdf[["gauge_id", "geometry"]]


def remove_files(paths: Iterable[str | Path], sidecars: bool = True) -> list[Path]:
    """Delete the given files, a shapefile's sidecars along with it.

    Deliberately takes an explicit list rather than a glob: the intermediates
    sit in the shared DEM directory, next to inputs that must survive.
    """
    removed = []
    for path in paths:
        path = Path(path)
        targets = sorted(path.parent.glob(path.stem + ".*")) if sidecars and path.suffix == ".shp" else [path]
        for target in targets:
            if target.exists():
                target.unlink()
                removed.append(target)
    return removed

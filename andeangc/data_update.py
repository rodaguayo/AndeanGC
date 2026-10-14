"""Extend the published streamflow datasets with recent records (notebook 01).

CAMELS-CL and PMET-obs both stop well before the present. Both functions here reindex the original
series out to the new end date and fill the gap with `combine_first`, so the
published values always win where the two overlap.
Only gauges already present in the original dataset are carried over

Every input is re-keyed to `gauge_id` before anything is joined, because the four files
reaching these functions are keyed three different ways: the DGA parquet by the bare
station code, the CAMELS-CL series by the bare code in its header, the PMET-obs series by
the ids of the release they were published in, and `SNHI_data.csv` by the `gauge_id` nb01
has just given it. Merging any two of those on their own spelling silently intersects to
nothing: the gap simply does not get filled, and the output looks like a normal run.

CAMELS-PE shares no key with SENAMHI_data.csv at all: its `PE_*` ids are its own, and the
ANDREA export carries no station code. Its gauges are therefore matched to ours by location.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from andeangc import config as cfg
from andeangc import data_homogenize


def update_camels_cl_data(original_file: str | Path, updated_parquet: str | Path,
                          output_file: str | Path) -> pd.DataFrame:
    """Update CAMELS_CL daily data by combining historical and recent data.

    Both inputs are keyed by the bare DGA station code, so both are stamped with the
    Chilean `gauge_id` on load and the merge happens in the id space the output is
    published in.
    """
    original_data = pd.read_csv(original_file, index_col='date', parse_dates=['date'])
    original_data.columns = data_homogenize.format_gauge_ids(
        original_data.columns, cfg.gauge_id_prefix_cl, cfg.gauge_id_zfill)
    original_data = original_data.reindex(pd.date_range(start=original_data.index.min(), end='2025-12-31', freq='D'))

    # load and pivot updated data
    updated_data = pd.read_parquet(updated_parquet)[['CODIGO ESTACION', 'FECHA', 'Caudal_diario']]
    updated_data["CODIGO ESTACION"] = data_homogenize.format_gauge_ids(
        updated_data["CODIGO ESTACION"], cfg.gauge_id_prefix_cl, cfg.gauge_id_zfill)
    updated_data = updated_data.drop_duplicates(subset=['FECHA', 'CODIGO ESTACION'], keep='first')
    updated_data = updated_data.pivot(index='FECHA', columns='CODIGO ESTACION', values='Caudal_diario')

    updated_data.index = pd.to_datetime(updated_data.index, format='%d/%m/%Y')
    updated_data = updated_data.sort_index()
    updated_data.index.name = "date"
    updated_data.columns.name = None

    # keep only stations that are in both datasets
    updated_data = updated_data[original_data.columns.intersection(updated_data.columns)]

    # merging
    final_data = original_data.combine_first(updated_data)
    final_data = final_data.round(3)
    final_data.to_csv(output_file, index_label='date')
    return final_data

def update_pmet_data(original_file: str | Path, updated_cl_file: str | Path,
                     updated_arg_file: str | Path, output_file: str | Path) -> pd.DataFrame:
    """
    Update PMET data by merging original data with updated Chile and Argentina datasets.

    Parameters:
    - original_file: path to original PMET data (1950-2020)
    - updated_cl_file: path to updated Chile data (parquet)
    - updated_arg_file: path to updated Argentina data (csv)
    - output_file: path to save the merged output

    PMET-obs spans both countries and is one source in the merge, so all three inputs are
    re-keyed to the PMET-obs prefix: the published series carry the ids of the release they
    came from, the DGA export arrives on bare station codes, and the Argentine file is
    already keyed for its own source.
    """
    # Load and reindex original data
    original_data = pd.read_csv(original_file, index_col=0)
    original_data.columns = data_homogenize.format_gauge_ids(
        original_data.columns, cfg.gauge_id_prefix_pa, cfg.gauge_id_zfill)
    original_data.index = pd.to_datetime(original_data.index)
    original_data = original_data.reindex(pd.date_range(start=original_data.index.min(), end='2025-12-31', freq='D'))
    original_data.index.name = "date"

    # Load and pivot updated Chile data
    updated_data_cl = pd.read_parquet(updated_cl_file)[['CODIGO ESTACION', 'FECHA', 'Caudal_diario']]
    updated_data_cl["CODIGO ESTACION"] = data_homogenize.format_gauge_ids(
        updated_data_cl["CODIGO ESTACION"], cfg.gauge_id_prefix_pa, cfg.gauge_id_zfill)
    updated_data_cl = updated_data_cl.drop_duplicates(subset=['FECHA', 'CODIGO ESTACION'], keep='first')
    updated_data_cl = updated_data_cl.pivot(index='FECHA', columns='CODIGO ESTACION', values='Caudal_diario')
    updated_data_cl.index = pd.to_datetime(updated_data_cl.index, format='%d/%m/%Y')
    updated_data_cl = updated_data_cl.sort_index()
    updated_data_cl.index.name = "date"
    updated_data_cl.columns.name = None
    updated_data_cl = updated_data_cl[original_data.columns.intersection(updated_data_cl.columns)]

    # Load updated Argentina data, keyed for Argentina and re-keyed for PMET-obs
    updated_data_arg = pd.read_csv(updated_arg_file, index_col="date", parse_dates=['date'])
    updated_data_arg.columns = data_homogenize.format_gauge_ids(
        updated_data_arg.columns, cfg.gauge_id_prefix_pa, cfg.gauge_id_zfill)
    updated_data_arg = updated_data_arg[original_data.columns.intersection(updated_data_arg.columns)]

    # Merge and save
    updated_data = pd.concat([updated_data_cl, updated_data_arg], axis=1)
    final_data = original_data.combine_first(updated_data).round(3)
    final_data.to_csv(output_file, index_label='date')

    return final_data


def match_gauges(ours: pd.DataFrame, theirs: pd.DataFrame, max_distance_km: float) -> pd.Series:
    """Map each gauge in `theirs` to the nearest gauge in `ours` within `max_distance_km`.

    Both frames are indexed by their own ids and carry `gauge_lat` / `gauge_lon`. Distance is
    great-circle, so no projection is involved. Returns `their id -> our id`; a gauge with no
    match is left out, and two of theirs claiming the same gauge of ours raises.
    """
    lat1, lon1 = np.radians(theirs.gauge_lat.to_numpy())[:, None], np.radians(theirs.gauge_lon.to_numpy())[:, None]
    lat2, lon2 = np.radians(ours.gauge_lat.to_numpy())[None, :], np.radians(ours.gauge_lon.to_numpy())[None, :]
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    distance = 2 * 6371.0 * np.arcsin(np.sqrt(h))

    nearest = distance.argmin(axis=1)
    within = distance.min(axis=1) <= max_distance_km
    matches = pd.Series(ours.index[nearest[within]], index=theirs.index[within])
    if matches.duplicated().any():
        raise ValueError(f"several gauges matched to one: {matches[matches.duplicated(keep=False)].to_dict()}")
    return matches


def update_senamhi_data(original_file: str | Path, metadata_file: str | Path,
                        camels_stations_file: str | Path, camels_attributes_file: str | Path,
                        camels_timeseries_file: str | Path, output_file: str | Path) -> pd.DataFrame:
    """Fill the gaps in SENAMHI_data.csv with the observed flow of CAMELS-PE.

    Parameters:
    - original_file: SENAMHI_data.csv, keyed by gauge_id (m3/s)
    - metadata_file: SENAMHI_metadata.csv, for the gauge coordinates
    - camels_stations_file: CAMELS-PE stations.csv, for its gauge coordinates
    - camels_attributes_file: CAMELS-PE topographic_attributes.csv, for the catchment area
    - camels_timeseries_file: CAMELS-PE timeseries.csv (long format, flow_obs in mm/d)
    - output_file: path to save the merged output

    CAMELS-PE gauges are matched to ours within `camels_pe_max_distance` km, and `flow_obs` is
    converted back to m3/s with the CAMELS-PE catchment area — the area it was normalised by.
    The output runs to the end of the CAMELS-PE record (2025), past `period_q`, like the other
    updates here.
    """
    original_data = pd.read_csv(original_file, index_col='date', parse_dates=['date'])

    ours = pd.read_csv(metadata_file, index_col='gauge_id').loc[original_data.columns]
    theirs = pd.read_csv(camels_stations_file, index_col='gauge_id')
    matches = match_gauges(ours, theirs, cfg.camels_pe_max_distance)
    area = pd.read_csv(camels_attributes_file, index_col='gauge_id')['area']

    # load, pivot and convert mm/d -> m3/s
    updated_data = pd.read_csv(camels_timeseries_file, usecols=['date', 'gauge_id', 'flow_obs'], parse_dates=['date'])
    updated_data = updated_data[updated_data.gauge_id.isin(matches.index)]
    updated_data = updated_data.pivot(index='date', columns='gauge_id', values='flow_obs')
    updated_data = updated_data * area[updated_data.columns] / 86.4
    updated_data = updated_data.rename(columns=matches)
    updated_data.columns.name = None

    # merging, out to the end of the CAMELS-PE record; nb03 slices to period_q
    final_data = original_data.combine_first(updated_data)[original_data.columns]
    final_data = final_data.asfreq('D')
    final_data = final_data.round(3)
    final_data.to_csv(output_file, index_label='date')
    return final_data

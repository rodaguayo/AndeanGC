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
"""

from pathlib import Path

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

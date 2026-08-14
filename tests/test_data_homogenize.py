"""The two parsers that make sense of the raw ANA/SENAMHI workbooks.

Both are exercised on synthetic workbooks in the layout the ANA portal produces,
so these tests need no access to the real data.
"""

import pandas as pd

from andeangc import data_homogenize


def write_workbook(path, meta_rows, data_rows):
    """Write a workbook in the ANA layout: metadata block, then a year x day grid.

    The metadata block occupies rows 0-12, the data header sits on row 13 and the
    rows follow — the offsets `extract_metadata` (nrows=15) and
    `extract_timeseries_data` (header=13) both assume.
    """
    grid = [[None, None] + [None] * 12 for _ in range(13)]
    for i, (key, value) in enumerate(meta_rows):
        grid[i][0], grid[i][1] = key, value
    header = ["Año", "Día"] + ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    pd.DataFrame(grid + [header] + data_rows).to_excel(path, index=False, header=False)
    return path


def test_extract_metadata_splits_the_combined_coordinate_string(tmp_path):
    """Lat, lon and altitude arrive as one '/'-joined string in a single cell."""
    path = write_workbook(
        tmp_path / "Estacion.xlsx",
        [("Estación", "PUENTE CARRETERA"),
         ("Operador", "SENAMHI"),
         ("Coordenadas geográficas", "Latitud: -7.726 / Longitud: -77.665 / Altitud(msnm): 1200")],
        [[2020, 1] + [1.0] * 12],
    )

    meta = data_homogenize.extract_metadata(path)

    assert meta["gauge_name"] == "PUENTE CARRETERA"
    assert meta["operator"] == "SENAMHI"
    assert meta["gauge_lat"] == "-7.726"
    assert meta["gauge_lon"] == "-77.665"
    assert meta["altitude"] == "1200"
    assert meta["file_path"] == "Estacion.xlsx"


def test_extract_metadata_reports_none_for_absent_fields(tmp_path):
    """A workbook without coordinates must parse, not raise."""
    path = write_workbook(tmp_path / "Estacion.xlsx",
                          [("Estación", "SIN COORDENADAS")],
                          [[2020, 1] + [1.0] * 12])

    meta = data_homogenize.extract_metadata(path)

    assert meta["gauge_name"] == "SIN COORDENADAS"
    assert meta["gauge_lat"] is None
    assert meta["gauge_lon"] is None


def test_extract_timeseries_drops_the_impossible_dates_of_the_rectangular_grid(tmp_path):
    """The grid is 31 rows x 12 columns, so it asserts 31 February exists.

    Day 31 is real in 7 months only. The other 5 cells hold values in the sheet
    and must be discarded rather than shifted onto a neighbouring date.
    """
    path = write_workbook(tmp_path / "Estacion.xlsx",
                          [("Estación", "GRID")],
                          [[2020, 31] + [5.0] * 12])

    series = data_homogenize.extract_timeseries_data(path, {"gauge_name": "GRID"})

    assert series.notna().sum() == 7
    kept = set(series.dropna().index.month)
    assert kept == {1, 3, 5, 7, 8, 10, 12}
    assert pd.Timestamp("2020-02-29") not in series.dropna().index


def test_extract_timeseries_reindexes_onto_a_gap_free_daily_range(tmp_path):
    """Missing days must be present as NaN, so downstream counts are honest."""
    path = write_workbook(tmp_path / "Estacion.xlsx",
                          [("Estación", "GAPS")],
                          [[2020, 1] + [2.0] + [None] * 11,
                           [2020, 2] + [None] * 11 + [3.0]])

    series = data_homogenize.extract_timeseries_data(path, {"gauge_name": "GAPS"})

    assert series.index.min() == pd.Timestamp("2020-01-01")
    assert series.index.max() == pd.Timestamp("2020-12-02")
    assert series.index.is_monotonic_increasing
    assert (series.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()
    assert series.notna().sum() == 2


def test_process_excel_files_skips_a_broken_workbook(tmp_path):
    """One malformed export must not lose the rest of the batch."""
    good = write_workbook(tmp_path / "good.xlsx", [("Estación", "GOOD")], [[2020, 1] + [1.0] * 12])
    bad = tmp_path / "bad.xlsx"
    bad.write_text("not an excel file")

    metadata, timeseries = data_homogenize.process_excel_files([good, bad])

    assert len(metadata) == 1
    assert metadata.iloc[0]["gauge_name"] == "GOOD"
    assert list(timeseries.columns) == ["GOOD"]


def test_process_excel_files_on_no_input_returns_empty_frames():
    metadata, timeseries = data_homogenize.process_excel_files([])

    assert metadata.empty
    assert timeseries.empty

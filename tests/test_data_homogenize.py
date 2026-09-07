"""The parsers that make sense of the raw provider workbooks.

Each is exercised on synthetic workbooks in the layout its provider produces — the
ANA portal for SENAMHI, the SNHI export for Argentina — so these tests need no
access to the real data.
"""

import pandas as pd
import pytest

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


def test_registry_ids_survive_a_renumbered_download(tmp_path):
    """The bug: ids came from DatosSerie(N).xlsx, so re-downloading renumbered gauges."""
    registry = tmp_path / "registry.csv"
    registry.write_text("gauge_name,gauge_id\nCondorcerro,P00000008\nOcona,P00000040\n")

    # Same stations, read back in a different order — ids must not move.
    assert data_homogenize.assign_gauge_ids(
        ["Ocona", "Condorcerro"], registry, "P", 8) == ["P00000040", "P00000008"]


def test_registry_assigns_the_lowest_free_id_and_records_it(tmp_path):
    registry = tmp_path / "registry.csv"
    registry.write_text("gauge_name,gauge_id\nCondorcerro,P00000002\n")

    got = data_homogenize.assign_gauge_ids(["Zulia", "Condorcerro", "Ancash"], registry, "P", 8)
    # New names are numbered in sorted order, skipping the taken 2, and persisted.
    assert got == ["P00000003", "P00000002", "P00000001"]
    assert registry.read_text().splitlines()[1:] == [
        "Ancash,P00000001", "Condorcerro,P00000002", "Zulia,P00000003"]


def test_missing_registry_raises_rather_than_renumbering(tmp_path):
    """The registry is not in git, so absent means lost — never a licence to reassign ids."""
    with pytest.raises(FileNotFoundError, match="renumber every Peruvian gauge"):
        data_homogenize.assign_gauge_ids(["A"], tmp_path / "gone.csv", "P", 8)


def test_bare_station_codes_become_gauge_ids():
    """The one spelling of the join key: prefix, zero-padded to a fixed width. Codes
    reach it as ints (the DGA parquet), as strings (a CSV header) and already at full
    width — all three must land on the same id."""
    assert data_homogenize.format_gauge_ids([101, "101"], "X", 8) == ["X00000101", "X00000101"]
    assert data_homogenize.format_gauge_ids([12345678], "X", 8) == ["X12345678"]
    assert data_homogenize.format_gauge_ids([7], "P", 8) == ["P00000007"]


def test_an_id_that_already_carries_a_prefix_is_re_keyed():
    """Sources reach the join in three states, and all three must land on the same id.
    Re-stamping with the same prefix is a no-op, so `pixi run pipeline` runs twice; with
    another prefix it re-keys, which is how PMET-obs's published series and the Argentine
    file nb01 has just written reach one id space in `update_pmet_data`."""
    assert data_homogenize.format_gauge_ids(["X00000101"], "X", 8) == ["X00000101"]
    assert data_homogenize.format_gauge_ids(["A00001807"], "M", 8) == ["M00001807"]
    assert data_homogenize.format_gauge_ids([1807, "1807", "A00001807"], "M", 8) == ["M00001807"] * 3


def test_a_code_that_arrived_as_a_decimal_raises():
    """`str(i).zfill(8)` would emit X001234.0 here — an id that joins to nothing."""
    with pytest.raises(ValueError):
        data_homogenize.format_gauge_ids(["1234.0"], "X", 8)


def test_a_provider_table_is_rekeyed_and_keeps_the_institutional_code():
    table = pd.DataFrame({"gauge_id": [1001001, 12345678], "gauge_name": ["A", "B"]})

    got = data_homogenize.stamp_gauge_ids(table, "X", 8)

    assert list(got.columns) == ["gauge_id", "gauge_id_source", "gauge_name"]
    assert list(got.gauge_id) == ["X01001001", "X12345678"]
    assert list(got.gauge_id_source) == [1001001, 12345678]


def test_stamping_an_already_stamped_table_is_a_no_op():
    """nb01 rewrites the CAMELS files under their own names, so `pixi run pipeline`
    stamps them again on the next run. Without gauge_id_source that raises."""
    table = pd.DataFrame({"gauge_id": [1001001], "gauge_name": ["A"]})

    once = data_homogenize.stamp_gauge_ids(table, "X", 8)
    twice = data_homogenize.stamp_gauge_ids(once, "X", 8)

    pd.testing.assert_frame_equal(once, twice)


def write_snhi_workbook(path, title, rows):
    """Write a workbook in the SNHI layout: a title row, then a two-column daily table.

    The title is the only place the station number appears; the table header sits on
    row 1, the offset `read_snhi_files` assumes.
    """
    frame = pd.DataFrame(rows, columns=["Fecha y Hora", "Caudal Medio Diario [m3/seg]"])
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([[title, None]]).to_excel(writer, index=False, header=False, startrow=0)
        frame.to_excel(writer, index=False, startrow=1)
    return path


def test_snhi_station_number_comes_from_the_title_row(tmp_path):
    """The file name carries no code, so the title row is the only source of the id."""
    path = write_snhi_workbook(
        tmp_path / "Historicos-Estacion 1001.xlsx",
        "Datos Historicos - Estacion 1001 - Vinchina - Vinchina",
        [["01/09/2016 05:00", 0.23], ["02/09/2016 05:00", 0.18]])

    data = data_homogenize.read_snhi_files([path], "X", 8)

    assert list(data.columns) == ["X00001001"]
    assert data.index.name == "date"
    assert list(data.index) == [pd.Timestamp("2016-09-01"), pd.Timestamp("2016-09-02")]
    assert list(data["X00001001"]) == [0.23, 0.18]


def test_snhi_days_are_truncated_and_the_first_record_of_a_day_wins(tmp_path):
    """The export is timestamped, the dataset is daily: two records on one day is one row."""
    path = write_snhi_workbook(
        tmp_path / "Estacion.xlsx", "Estacion 7 - Rio - Lugar",
        [["01/09/2016 05:00", 1.0], ["01/09/2016 17:00", 99.0], ["02/09/2016 05:00", 2.0]])

    data = data_homogenize.read_snhi_files([path], "X", 8)

    assert list(data["X00000007"]) == [1.0, 2.0]


def test_snhi_unreadable_dates_and_flows_do_not_reach_the_frame(tmp_path):
    """A missing flow must be NaN on its date; a row with no usable date must be dropped."""
    path = write_snhi_workbook(
        tmp_path / "Estacion.xlsx", "Estacion 7 - Rio - Lugar",
        [["01/09/2016 05:00", "s/d"], ["sin fecha", 5.0], ["03/09/2016 05:00", 3.0]])

    data = data_homogenize.read_snhi_files([path], "X", 8)

    assert list(data.index) == [pd.Timestamp("2016-09-01"), pd.Timestamp("2016-09-03")]
    assert data["X00000007"].isna().sum() == 1


def test_snhi_workbook_without_a_station_number_is_skipped_not_guessed(tmp_path):
    """An unidentified workbook used to land in the frame as an "UNKNOWN" column, which
    a second one would then duplicate. Losing it loudly is the lesser evil."""
    named = write_snhi_workbook(tmp_path / "a.xlsx", "Estacion 12 - Rio - Lugar",
                                [["01/09/2016 05:00", 1.0]])
    unnamed = write_snhi_workbook(tmp_path / "b.xlsx", "Datos Historicos",
                                  [["01/09/2016 05:00", 2.0]])

    data = data_homogenize.read_snhi_files([named, unnamed], "X", 8)

    assert list(data.columns) == ["X00000012"]


def test_snhi_on_no_input_returns_an_empty_frame():
    assert data_homogenize.read_snhi_files([], "X", 8).empty

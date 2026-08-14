"""The merge that extends a published dataset with a rolling portal export.

The invariant worth pinning is `combine_first`'s direction: the published record
is authoritative, the portal export only fills gaps. Getting this backwards would
silently rewrite the curated values with provisional ones.
"""

import pandas as pd

from andeangc import data_update


def write_original(path, index, columns, value):
    df = pd.DataFrame(value, index=pd.DatetimeIndex(index, name="date"), columns=columns)
    df.to_csv(path, index_label="date")
    return path


def write_dga_export(path, rows):
    """The DGA parquet: long format, dd/mm/YYYY dates, station code as a column."""
    pd.DataFrame(rows, columns=["CODIGO ESTACION", "FECHA", "Caudal_diario"]).to_parquet(path)
    return path


def test_published_values_win_over_the_portal_export(tmp_path):
    original = write_original(tmp_path / "o.csv", ["2020-01-01", "2020-01-02"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet",
                               [["101", "01/01/2020", 999.0],     # overlaps a published day
                                ["101", "03/01/2020", 7.0]])      # fills a gap

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert out.loc["2020-01-01", "101"] == 1.0    # published value survives
    assert out.loc["2020-01-03", "101"] == 7.0    # gap filled from the export


def test_stations_absent_from_the_published_set_are_not_introduced(tmp_path):
    """These functions extend a curated station list; they must not grow it."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet",
                               [["101", "02/01/2020", 2.0],
                                ["999", "02/01/2020", 5.0]])      # unknown station

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert list(out.columns) == ["101"]


def test_duplicate_rows_in_the_export_do_not_break_the_pivot(tmp_path):
    """The portal repeats rows; a bare pivot would raise on the duplicate index."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet",
                               [["101", "02/01/2020", 2.0],
                                ["101", "02/01/2020", 3.0]])      # same day twice

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert out.loc["2020-01-02", "101"] == 2.0    # first occurrence kept


def test_the_series_is_extended_to_the_new_horizon(tmp_path):
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet", [["101", "01/01/2020", 1.0]])

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert out.index.max() == pd.Timestamp("2025-12-31")


def test_pmet_prefixes_chilean_codes_before_joining(tmp_path):
    """PMET spans two countries: DGA codes are zero-padded behind an 'X', while
    the Argentine file already carries ids in that form. Both must land in the
    same frame, and the published values must still win on overlap."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01", "2020-01-02"],
                              ["X00000101", "X00002001"], 1.0)
    updated_cl = write_dga_export(tmp_path / "cl.parquet",
                                  [[101, "02/01/2020", 4.0],      # overlaps -> ignored
                                   [101, "03/01/2020", 8.0]])     # new day  -> kept
    updated_arg = tmp_path / "arg.csv"
    pd.DataFrame({"date": ["2020-01-03"], "X00002001": [9.0]}).to_csv(updated_arg, index=False)

    out = data_update.update_pmet_data(original, updated_cl, updated_arg, tmp_path / "out.csv")

    assert list(out.columns) == ["X00000101", "X00002001"]
    assert out.loc["2020-01-02", "X00000101"] == 1.0    # published value wins
    assert out.loc["2020-01-03", "X00000101"] == 8.0    # Chilean gap filled
    assert out.loc["2020-01-03", "X00002001"] == 9.0    # Argentine gap filled

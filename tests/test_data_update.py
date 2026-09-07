"""The merge that extends a published dataset with a rolling portal export.

Two invariants worth pinning. `combine_first`'s direction: the published record is
authoritative, the portal export only fills gaps — getting this backwards would silently
rewrite the curated values with provisional ones. And the key the merge happens on: the
files arriving here are keyed three different ways (bare station codes, the ids of an
earlier release, the `gauge_id` nb01 has just assigned), so a merge on the spelling each
file arrived with intersects to nothing and fills no gap at all, without failing.

The expected ids are built from `config.yml` rather than spelled out, because that is
where the prefixes live; what the tests pin is that every input reaches the same id space,
not which letter it starts with. The spelling itself is pinned in `test_data_homogenize`.
"""

import pandas as pd

from andeangc import config as cfg
from andeangc import data_update


def cl_id(code):
    """A Chilean gauge_id, as `update_camels_cl_data` writes it."""
    return f"{cfg.gauge_id_prefix_cl}{int(code):0{cfg.gauge_id_zfill}d}"


def pa_id(code):
    """A PMET-obs gauge_id, as `update_pmet_data` writes it."""
    return f"{cfg.gauge_id_prefix_pa}{int(code):0{cfg.gauge_id_zfill}d}"


def ar_id(code):
    """An Argentine gauge_id — the key `SNHI_data.csv` reaches `update_pmet_data` with."""
    return f"{cfg.gauge_id_prefix_ar}{int(code):0{cfg.gauge_id_zfill}d}"


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

    assert out.loc["2020-01-01", cl_id(101)] == 1.0    # published value survives
    assert out.loc["2020-01-03", cl_id(101)] == 7.0    # gap filled from the export


def test_stations_absent_from_the_published_set_are_not_introduced(tmp_path):
    """These functions extend a curated station list; they must not grow it."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet",
                               [["101", "02/01/2020", 2.0],
                                ["999", "02/01/2020", 5.0]])      # unknown station

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert list(out.columns) == [cl_id(101)]


def test_duplicate_rows_in_the_export_do_not_break_the_pivot(tmp_path):
    """The portal repeats rows; a bare pivot would raise on the duplicate index."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet",
                               [["101", "02/01/2020", 2.0],
                                ["101", "02/01/2020", 3.0]])      # same day twice

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert out.loc["2020-01-02", cl_id(101)] == 2.0    # first occurrence kept


def test_the_series_is_extended_to_the_new_horizon(tmp_path):
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet", [["101", "01/01/2020", 1.0]])

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert out.index.max() == pd.Timestamp("2025-12-31")


def test_camels_output_is_keyed_by_gauge_id(tmp_path):
    """Both inputs are keyed by the bare DGA code; the output is the pipeline's own
    file, so it carries the prefixed join key nb03 merges on."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], ["101", "12345678"], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet", [["101", "02/01/2020", 2.0]])

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert list(out.columns) == [cl_id(101), cl_id(12345678)]
    assert list(pd.read_csv(tmp_path / "out.csv", nrows=0).columns) == ["date", cl_id(101), cl_id(12345678)]


def test_camels_fills_the_gap_when_the_original_arrives_already_keyed(tmp_path):
    """The published CAMELS-CL series are bare, but a re-run — or a file rewritten by an
    earlier version of this pipeline — hands over ids. The bare export must still reach
    them, rather than intersecting to nothing and quietly extending nothing."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], [cl_id(101)], 1.0)
    updated = write_dga_export(tmp_path / "u.parquet", [["101", "02/01/2020", 2.0]])

    out = data_update.update_camels_cl_data(original, updated, tmp_path / "out.csv")

    assert list(out.columns) == [cl_id(101)]
    assert out.loc["2020-01-02", cl_id(101)] == 2.0


def test_pmet_gathers_three_key_spellings_into_one(tmp_path):
    """PMET-obs is one source spanning two countries, and its three inputs arrive keyed
    three ways: the published series with the ids of the release they came from, the DGA
    export on bare station codes, and `SNHI_data.csv` with the Argentine gauge_id nb01
    just gave it. All three must land in the same frame, and the published values must
    still win on overlap."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01", "2020-01-02"],
                              ["X00000101", "X00002001"], 1.0)   # a previous release's ids
    updated_cl = write_dga_export(tmp_path / "cl.parquet",
                                  [[101, "02/01/2020", 4.0],      # overlaps -> ignored
                                   [101, "03/01/2020", 8.0]])     # new day  -> kept
    updated_arg = tmp_path / "arg.csv"
    pd.DataFrame({"date": ["2020-01-03"], ar_id(2001): [9.0]}).to_csv(updated_arg, index=False)

    out = data_update.update_pmet_data(original, updated_cl, updated_arg, tmp_path / "out.csv")

    assert list(out.columns) == [pa_id(101), pa_id(2001)]
    assert out.loc["2020-01-02", pa_id(101)] == 1.0     # published value wins
    assert out.loc["2020-01-03", pa_id(101)] == 8.0     # Chilean gap filled
    assert out.loc["2020-01-03", pa_id(2001)] == 9.0    # Argentine gap filled


def test_pmet_stations_absent_from_the_published_set_are_not_introduced(tmp_path):
    """Re-keying must widen the join, not the station list: an Argentine gauge PMET-obs
    never carried stays out, however it is spelled."""
    original = write_original(tmp_path / "o.csv", ["2020-01-01"], [pa_id(101)], 1.0)
    updated_cl = write_dga_export(tmp_path / "cl.parquet", [[999, "02/01/2020", 5.0]])
    updated_arg = tmp_path / "arg.csv"
    pd.DataFrame({"date": ["2020-01-02"], ar_id(2001): [9.0]}).to_csv(updated_arg, index=False)

    out = data_update.update_pmet_data(original, updated_cl, updated_arg, tmp_path / "out.csv")

    assert list(out.columns) == [pa_id(101)]

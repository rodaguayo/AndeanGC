"""The manifest checker, exercised on synthetic version directories.

These tests build their own `dataset_version.yml` and artifacts in `tmp_path`,
so they neither read nor depend on the real dataset.
"""

import pandas as pd
import pytest
import yaml

from andeangc import config as cfg
from andeangc import manifest


@pytest.fixture
def version_dir(tmp_path):
    """A minimal version directory whose manifest matches its artifacts."""
    gauges = [f"X{i:08d}" for i in range(3)]
    pd.DataFrame(index=pd.Index(gauges, name="gauge_id")).to_csv(tmp_path / "AndeanGC_metadata.csv")
    pd.DataFrame(1.0, index=pd.date_range("2020-01-01", periods=2, name="date"),
                 columns=gauges).to_csv(tmp_path / "AndeanGC_data.csv")

    climate = tmp_path / "climate" / "historical"
    climate.mkdir(parents=True)
    for var in ("prcp", "tas"):
        pd.DataFrame(1.0, index=pd.date_range("2020-01-01", periods=2), columns=gauges) \
          .to_parquet(climate / f"AndeanGC_{var}_ERA5.parquet")

    (tmp_path / "dataset_version.yml").write_text(yaml.safe_dump({
        "doi": "10.5281/zenodo.18035801",
        "variables": {
            "streamflow": [{"n_stations": 3, "period": [int(str(cfg.period_q[0])[:4]),
                                                        int(str(cfg.period_q[1])[:4])]}],
            "climate_historical": [{"name": "prcp", "period": [int(str(cfg.period_climate[0])[:4]),
                                                               int(str(cfg.period_climate[1])[:4])]},
                                   {"name": "tas", "period": [int(str(cfg.period_climate[0])[:4]),
                                                              int(str(cfg.period_climate[1])[:4])]}],
        },
        "pipeline": {"filtering": {"intervention_keywords": list(cfg.intervention_keywords),
                                   "glacier_threshold": cfg.glacier_threshold,
                                   "min_data_days": cfg.min_data_days}},
        "outputs": {"files": {"metadata": "AndeanGC_metadata.csv", "timeseries": "AndeanGC_data.csv"},
                    "climate_historical": ["AndeanGC_prcp_ERA5.parquet", "AndeanGC_tas_ERA5.parquet"]},
    }, allow_unicode=True))
    return tmp_path


def edit(version_dir, mutate):
    path = version_dir / "dataset_version.yml"
    mf = yaml.safe_load(path.read_text())
    mutate(mf)
    path.write_text(yaml.safe_dump(mf, allow_unicode=True))


def test_a_consistent_manifest_reports_nothing(version_dir):
    assert manifest.check(version_dir) == []


def test_station_count_is_checked_against_the_metadata(version_dir):
    edit(version_dir, lambda mf: mf["variables"]["streamflow"][0].update(n_stations=200))

    problems = manifest.check(version_dir)

    assert any("n_stations" in p and "200" in p and "3" in p for p in problems)


def test_a_fuzzy_station_count_is_rejected_rather_than_ignored(version_dir):
    """'~200' silently defeated the old manifest; it must be flagged, not skipped."""
    edit(version_dir, lambda mf: mf["variables"]["streamflow"][0].update(n_stations="~200"))

    assert any("n_stations" in p and "cannot be checked" in p for p in manifest.check(version_dir))


def test_intervention_keywords_must_match_config(version_dir):
    """The original drift: manifest said [dam, canal, ...], nb04 matched Spanish."""
    edit(version_dir, lambda mf: mf["pipeline"]["filtering"].update(
        intervention_keywords=["dam", "canal", "reservoir", "diversion"]))

    assert any("intervention_keywords" in p for p in manifest.check(version_dir))


def test_a_declared_file_that_does_not_exist_is_reported(version_dir):
    edit(version_dir, lambda mf: mf["outputs"]["files"].update(metadata="typo.csv"))

    assert any("typo.csv" in p and "missing" in p for p in manifest.check(version_dir))


def test_a_wrong_filename_does_not_silence_the_count_check(version_dir):
    """One drift must not mask another: n_stations is still checked."""
    def mutate(mf):
        mf["outputs"]["files"]["metadata"] = "typo.csv"
        mf["variables"]["streamflow"][0]["n_stations"] = 200
    edit(version_dir, mutate)

    problems = manifest.check(version_dir)

    assert any("typo.csv" in p for p in problems)
    assert any("n_stations" in p for p in problems)


def test_a_declared_variable_without_a_published_file_is_reported(version_dir):
    """How the vanished PET (`ep`) surfaced."""
    edit(version_dir, lambda mf: mf["variables"]["climate_historical"].append(
        {"name": "ep", "period": [int(str(cfg.period_climate[0])[:4]),
                                  int(str(cfg.period_climate[1])[:4])]}))

    assert any("[ep]" in p for p in manifest.check(version_dir))


def test_an_undeclared_parquet_is_reported(version_dir):
    (version_dir / "climate" / "historical" / "AndeanGC_stray_ERA5.parquet").write_bytes(b"")

    assert any("not declared" in p for p in manifest.check(version_dir))


def test_timeseries_and_metadata_gauge_sets_must_agree(version_dir):
    """Catches a stage re-run out of order, which is how the real one drifted."""
    data = pd.read_csv(version_dir / "AndeanGC_data.csv", index_col=0)
    data["X00000099"] = 1.0
    data.to_csv(version_dir / "AndeanGC_data.csv")

    assert any("re-run out of order" in p for p in manifest.check(version_dir))


def test_doi_is_checked_against_citation_cff(version_dir):
    edit(version_dir, lambda mf: mf.update(doi="10.5281/zenodo.99999999"))

    assert any("doi" in p for p in manifest.check(version_dir))


def test_assert_ok_raises_and_names_every_problem(version_dir):
    edit(version_dir, lambda mf: mf["variables"]["streamflow"][0].update(n_stations=200))

    with pytest.raises(AssertionError, match="n_stations"):
        manifest.assert_ok(version_dir)

"""The signature definitions, on series whose answer is known in advance.

A signature that is merely plausible is worthless — nobody reviewing the
published table can tell 0.62 from 0.71. Every case here is a series built so
that the correct value can be worked out by hand: constant flow is all
baseflow, an exponential recession has the constant it was built with, a
catchment whose flow is a fixed fraction of its precipitation has an elasticity
of exactly 1.
"""

import numpy as np
import pandas as pd
import pytest

from andeangc import hydro_signatures as hs

DECADE = pd.date_range("2000-04-01", "2010-03-31", freq="D")   # ten complete April-March years


def constant(value=2.0, index=DECADE):
    return pd.Series(float(value), index=index)


def test_one_cumec_over_one_square_kilometre_is_86_point_4_millimetres():
    assert hs.to_mm_per_day(pd.Series([1.0]), 1.0).iloc[0] == pytest.approx(86.4)
    assert hs.to_mm_per_day(pd.Series([1.0]), 86.4).iloc[0] == pytest.approx(1.0)


def test_the_water_year_starts_in_its_start_month():
    dates = pd.DatetimeIndex(["2001-03-31", "2001-04-01", "2002-03-31"])
    assert hs.water_year(dates, 4).tolist() == [2000, 2001, 2001]


def test_a_year_missing_half_its_days_is_not_a_complete_year():
    gappy = constant()
    gappy.loc["2003-04-01":"2003-09-30"] = np.nan

    kept = hs.complete_water_years(gappy.dropna(), start_month=4, min_coverage=0.9)

    assert 2003 not in set(hs.water_year(kept.index, 4))
    assert len(set(hs.water_year(kept.index, 4))) == 9


def test_constant_flow_is_entirely_baseflow_and_has_no_seasonality():
    flow = constant()

    assert hs.baseflow_index(flow) == pytest.approx(1.0)
    assert hs.slope_fdc(flow) == pytest.approx(0.0)
    assert hs.half_flow_date(flow, start_month=4) == pytest.approx(273, abs=1)   # 30 September
    assert hs.seasonality(flow)[1] == pytest.approx(0.0, abs=1e-3)


def test_all_the_flow_on_one_date_is_perfectly_seasonal():
    flow = pd.Series(0.0, index=DECADE)
    flow.loc[flow.index.dayofyear == 15] = 100.0

    mean_day, strength = hs.seasonality(flow)

    assert strength == pytest.approx(1.0, abs=1e-2)
    assert mean_day == pytest.approx(15, abs=1)


def test_a_half_flow_date_at_the_new_year_is_not_averaged_into_the_middle_of_it():
    flow = pd.Series(0.0, index=DECADE)
    flow.loc[flow.index.dayofyear == 1] = 100.0   # every April-March year crosses its half on 1 January

    assert hs.half_flow_date(flow, start_month=4) == pytest.approx(1, abs=1)


def test_the_annual_extremes_land_on_the_week_they_were_built_on():
    flow = constant(1.0)
    flow[np.isin(flow.index.dayofyear, range(340, 347))] = 10.0   # a high week centred on day 343
    flow[np.isin(flow.index.dayofyear, range(220, 227))] = 0.1    # a low week centred on day 223

    assert hs.max_flow_doy(flow, start_month=4, window=7) == pytest.approx(343, abs=1)
    assert hs.min_flow_doy(flow, start_month=4, window=7) == pytest.approx(223, abs=1)


def test_a_one_day_spike_does_not_carry_the_flood_date():
    flow = constant(1.0)
    flow[np.isin(flow.index.dayofyear, range(100, 107))] = 5.0    # a sustained week
    flow[flow.index.dayofyear == 200] = 20.0                      # a taller single day

    assert flow.groupby(hs.water_year(flow.index, 4)).idxmax().iloc[0].dayofyear == 200
    assert hs.max_flow_doy(flow, start_month=4, window=7) == pytest.approx(103, abs=1)


def test_the_window_is_seven_calendar_days_not_seven_observations():
    """An isolated reading next to a gap is not a week, however high it is."""
    flow = constant(1.0)
    flow[np.isin(flow.index.dayofyear, range(100, 107))] = 5.0    # a real, fully observed week
    flow[flow.index.dayofyear == 200] = 1000.0
    flow = flow[~np.isin(flow.index.dayofyear, [*range(194, 200), *range(201, 207)])]

    # counting rows instead of days averages that one reading with a fortnight of baseline
    naive = flow.rolling(7, center=True).mean()
    assert naive.max() == pytest.approx((1000 + 6) / 7)   # and the week that never happened wins

    assert hs.max_flow_doy(flow, start_month=4, window=7) == pytest.approx(103, abs=1)


def test_extremes_either_side_of_the_new_year_average_to_the_new_year():
    flow = pd.Series(1.0, index=DECADE)
    for i, year in enumerate(sorted(set(hs.water_year(DECADE, 4)))):
        centre = pd.Timestamp(year=year, month=12, day=31) if i % 2 == 0 else \
                 pd.Timestamp(year=year + 1, month=1, day=8)
        flow.loc[centre - pd.Timedelta(days=3):centre + pd.Timedelta(days=3)] = 10.0

    # the per-year peaks alternate between day ~365 and day 8; their arithmetic mean is July
    assert hs.max_flow_doy(flow, start_month=4, window=7) == pytest.approx(4, abs=2)


def test_an_exponential_recession_returns_the_constant_it_was_built_with():
    days_into_spell = np.arange(len(DECADE)) % 60
    flow = pd.Series(10 * np.exp(-0.05 * days_into_spell), index=DECADE)

    assert hs.recession_constant(flow, min_length=5) == pytest.approx(0.05)


def test_flow_spells_are_counted_per_year_and_measured_in_days():
    flow = constant(1.0)
    for year in range(2000, 2010):
        flow.loc[f"{year}-07-01":f"{year}-07-03"] = 100.0    # three days above 9 x median

    frequency, duration = hs.high_flow_stats(flow, factor=9)

    # 30 spell-days over 3652 observed days, at 365.25 days to the year: 3.0004, not
    # quite 3, because the decade is two leap days longer than ten 365.25-day years.
    assert frequency == pytest.approx(30 / len(flow) * 365.25)
    assert frequency == pytest.approx(3.0, rel=1e-3)
    assert duration == pytest.approx(3.0)


def test_a_gappy_year_does_not_dilute_the_frequency():
    """The frequency is per day observed, not per water year admitted.

    Both records hold the same ten spells; the second is missing a fifth of every
    August, which `complete_water_years` still admits at 0.9 coverage. Counting
    that year as a whole one would report the same rate for a record that measured
    fewer days — the bias Addor's reference implementation removed by dividing by
    observed days. The gappy record must therefore show the *higher* rate.
    """
    flow = constant(1.0)
    for year in range(2000, 2010):
        flow.loc[f"{year}-07-01":f"{year}-07-03"] = 100.0

    gappy = flow.copy()
    for year in range(2000, 2010):
        gappy.loc[f"{year}-08-01":f"{year}-08-20"] = np.nan  # 200 days, spells untouched

    observed = gappy.dropna()
    assert len(hs.complete_water_years(observed, start_month=4, min_coverage=0.9)) == len(observed)

    dense, _ = hs.high_flow_stats(flow, factor=9)
    sparse, _ = hs.high_flow_stats(observed, factor=9)

    assert sparse > dense
    assert sparse == pytest.approx(30 / (len(flow) - 200) * 365.25)


def test_high_flow_is_a_multiple_of_the_median_and_low_flow_of_the_mean():
    """The two thresholds are taken from different statistics, which only shows on a
    skewed series — on the constant one above the mean and the median coincide, so
    swapping them changes nothing.

    Each year: 245 days at 1.0, a 90-day season at 10.0 and a 30-day one at 0.5, so
    the median is 1.0 and the mean (245 + 900 + 15) / 365 = 3.18. The high threshold
    is 9 x 1.0 = 9, which the wet season clears; on the mean it would be 28.6 and
    nothing would clear it. The low threshold is 0.2 x 3.18 = 0.64, which the dry
    season falls under; on the median it would be 0.2 and nothing would fall under it.
    """
    flow = pd.Series(1.0, index=DECADE)
    for year in range(2000, 2010):
        flow.loc[f"{year}-10-01":f"{year}-12-29"] = 10.0     # 90 days, one spell a year
    flow.loc[flow.index.month == 6] = 0.5                    # 30 days, one spell a year

    assert flow.median() == 1.0
    assert flow.mean() == pytest.approx(3.18, abs=0.01)

    assert hs.high_flow_stats(flow, factor=9) == pytest.approx((90.0, 90.0), rel=1e-3)
    assert hs.low_flow_stats(flow, factor=0.2) == pytest.approx((30.0, 30.0), rel=1e-3)


def test_percentiles_are_non_exceedance_so_q95_is_the_high_flow():
    flow = pd.Series(np.arange(1, 101, dtype=float), index=pd.date_range("2000-01-01", periods=100))

    assert hs.flow_percentile(flow, 0.95) > hs.flow_percentile(flow, 0.05)
    assert hs.flow_percentile(flow, 0.05) == pytest.approx(5.95)


def test_a_log_uniform_flow_duration_curve_has_a_slope_of_ln_10():
    """Flows spanning exactly one decade, log-uniformly: log Q is then linear in
    the percentile, so the slope is ln(10) per unit percentile whichever pair of
    percentiles bounds it. The constant-flow case below gives 0.0, which any sign
    convention and any normalisation also give; this one pins both.
    """
    flow = pd.Series(10 ** np.linspace(0, 1, len(DECADE)), index=DECADE)

    assert hs.slope_fdc(flow) == pytest.approx(np.log(10), rel=1e-6)
    assert hs.slope_fdc(flow, 0.2, 0.8) == pytest.approx(np.log(10), rel=1e-6)


def test_zero_flows_are_excluded_from_the_log_slope():
    flow = constant()
    flow.iloc[:365] = 0.0

    assert hs.slope_fdc(flow) == pytest.approx(0.0)      # the non-zero remainder is constant


def test_runoff_ratio_and_elasticity_on_a_catchment_that_tracks_its_forcing():
    rainfall = pd.Series(4.0, index=DECADE)
    flow = rainfall * 0.5

    assert hs.runoff_ratio(flow, rainfall) == pytest.approx(0.5)

    varying = pd.Series([2.0 + (year - 2000) / 5 for year in hs.water_year(DECADE, 4)], index=DECADE)
    assert hs.stream_elasticity(varying * 0.5, varying, 4, 0.9) == pytest.approx(1.0)


def test_one_freak_year_does_not_carry_the_elasticity():
    """Elasticity is the median of the per-year ratios, not their mean, because one
    year whose precipitation lands on the ten-year mean has a near-zero denominator
    and an arbitrarily large ratio. Here that year alone reaches 45; the mean of the
    ten years is 5.8, and the median stays near the 1.0 the clean record gives.
    """
    rainfall = pd.Series([2.0 + (year - 2000) / 5 for year in hs.water_year(DECADE, 4)], index=DECADE)
    flow = rainfall * 0.5
    freak = flow.copy()
    freak[hs.water_year(DECADE, 4).to_numpy() == 2005] *= 3.0

    clean = hs.stream_elasticity(flow, rainfall, 4, 0.9)
    out = hs.stream_elasticity(freak, rainfall, 4, 0.9)

    assert clean == pytest.approx(1.0)
    assert abs(out - clean) < 1.0        # the mean would move it by 4.8


def test_a_short_record_reports_its_length_instead_of_signatures():
    short = constant(index=pd.date_range("2000-04-01", "2003-03-31", freq="D"))

    out = hs.signatures(short, min_years=5)

    assert out == {"sig_n_years": 3}


def test_the_full_set_is_returned_for_a_long_enough_record():
    out = hs.signatures(constant(), p=constant(4.0))

    assert out["sig_n_years"] == 10
    assert out["q_mean"] == pytest.approx(2.0)
    assert out["runoff_ratio"] == pytest.approx(0.5)
    assert out["baseflow_index"] == pytest.approx(1.0)
    assert set(out) == {"sig_n_years", "q_mean", "runoff_ratio", "stream_elas", "slope_fdc",
                        "baseflow_index", "q5", "q95", "high_q_freq", "high_q_dur", "low_q_freq", "low_q_dur",
                        "hfd_mean", "q_max_doy", "q_min_doy", "q_centroid_doy", "seasonality", "recession_k"}

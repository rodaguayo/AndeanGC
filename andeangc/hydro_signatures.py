"""Hydrological signatures from a daily streamflow series.

The CAMELS signature set (Addor et al. 2017), computed one
gauge at a time by `signatures`. Five signatures go
beyond that set:
`q_max_doy`, `q_min_doy`, `q_centroid_doy`, `seasonality` and `recession_k`.

Everything except `to_mm_per_day` expects a daily `pd.Series` indexed by date
and expressed in **mm/day** — a depth, not a discharge. 

Two conventions are worth stating because the literature disagrees on both:

- **Percentiles are non-exceedance.** `flow_percentile(q, 0.95)` is a *high*
  flow, exceeded 5% of the time. CAMELS reports `q95` the same way.
- **`slope_fdc` is positive** for a normal catchment: it is measured between
  the 33rd and 66th non-exceedance percentiles of the log flows, in the
  direction of increasing flow. That is the `sfdc_addor_2017` variant — the one
  the CAMELS paper published — and deliberately not `sfdc_sawicz_2011`, which
  Addor's reference code returns by default and which reads the same two
  percentiles as *exceedance* probabilities.

Signatures are computed over complete water years only. A gauge whose record
holds fewer than `min_years` of them gets NaN rather than a number computed
from four wet seasons — see `complete_water_years`.
"""

import numpy as np
import pandas as pd

SECONDS_PER_DAY = 86400
DAYS_PER_YEAR = 365.25


def to_mm_per_day(discharge: pd.Series | pd.DataFrame, basin_area: float | pd.Series) -> pd.Series | pd.DataFrame:
    """Convert m3/s to mm/day over a basin area in km2.

    1 m3/s over 1 km2 is 86.4 mm/day. Accepts a frame of gauges with a matching
    Series of areas, in which case the columns and the index must align.
    """
    return discharge * SECONDS_PER_DAY / 1e6 * 1e3 / basin_area


def water_year(index: pd.DatetimeIndex, start_month: int) -> pd.Series:
    """The water year each date belongs to, labelled by its starting calendar year."""
    return pd.Series(np.where(index.month >= start_month, index.year, index.year - 1), index=index)


def complete_water_years(q: pd.Series, start_month: int, min_coverage: float) -> pd.Series:
    """The series restricted to water years that are `min_coverage` observed.

    Coverage is measured against the number of days the water year actually
    has, so a leap year is not penalised. Everything downstream works on the
    output of this function: a signature is only ever a statement about years
    the gauge actually recorded.
    """
    years = water_year(q.index, start_month)
    observed = q.groupby(years).count()
    length = q.groupby(years).apply(lambda block: (block.index.max() - block.index.min()).days + 1)
    expected = pd.Series([366 if _is_leap_water_year(year, start_month) else 365 for year in observed.index],
                         index=observed.index)
    keep = observed.index[(observed / expected >= min_coverage) & (length / expected >= min_coverage)]
    return q[years.isin(keep)]


def _is_leap_water_year(year: int, start_month: int) -> bool:
    """Whether the water year starting in `year` contains a 29 February."""
    leap_year = year if start_month <= 2 else year + 1
    return bool(pd.Timestamp(year=leap_year, month=1, day=1).is_leap_year)


def q_mean(q: pd.Series) -> float:
    """Mean daily flow (mm/day)."""
    return float(q.mean())


def runoff_ratio(q: pd.Series, p: pd.Series) -> float:
    """Mean flow over mean precipitation, on the days both are observed."""
    both = pd.concat([q, p], axis=1, join="inner").dropna()
    if both.empty:
        return np.nan
    return float(both.iloc[:, 0].mean() / both.iloc[:, 1].mean())


def stream_elasticity(q: pd.Series, p: pd.Series, start_month: int, min_coverage: float) -> float:
    """Streamflow elasticity to precipitation (Sankarasubramanian et al. 2001).

    The median annual proportional change in flow per proportional change in
    precipitation. 1 means flow tracks precipitation exactly; above 1 means the
    catchment amplifies it. Years where precipitation equals its own mean are
    dropped rather than producing a division by zero.
    """
    both = pd.concat([q.rename("q"), p.rename("p")], axis=1, join="inner").dropna()
    if both.empty:
        return np.nan

    both = both.loc[complete_water_years(both.q, start_month, min_coverage).index]
    years = water_year(both.index, start_month)
    annual = both.groupby(years).mean()
    if len(annual) < 2:
        return np.nan

    dq = annual.q - annual.q.mean()
    dp = annual.p - annual.p.mean()
    elasticity = (dq / dp.replace(0, np.nan)) * (annual.p.mean() / annual.q.mean())
    return float(elasticity.median())


def flow_percentile(q: pd.Series, quantile: float) -> float:
    """A non-exceedance percentile of daily flow (mm/day): 0.95 is a high flow."""
    return float(q.quantile(quantile))


def slope_fdc(q: pd.Series, lower: float = 0.33, upper: float = 0.66) -> float:
    """Slope of the flow duration curve between two log-flow percentiles.

    Steep means a flashy catchment, flat means a well-buffered one. Zero flows
    have no logarithm and are excluded; a catchment whose 33rd percentile is
    zero has no defined slope and returns NaN.
    """
    positive = q[q > 0]
    if positive.empty:
        return np.nan

    low, high = positive.quantile(lower), positive.quantile(upper)
    if low <= 0 or high <= 0:
        return np.nan
    return float((np.log(high) - np.log(low)) / (upper - lower))


def baseflow_index(q: pd.Series, alpha: float = 0.925, passes: int = 3, reflect: int = 30) -> float:
    """Fraction of flow that is baseflow, by the Lyne-Hollick filter.

    Three alternating passes with reflected ends, as recommended by Ladson et
    al. (2013) — a single forward pass leaves the result dependent on where the
    record happens to start. Gaps are not interpolated across: the filter runs
    on each contiguous block of observations longer than the reflection, and the
    index is the ratio of the summed baseflow to the summed flow.
    """
    baseflow_total, flow_total = 0.0, 0.0

    for block in _contiguous_blocks(q):
        if len(block) <= 2 * reflect:
            continue
        baseflow = _lyne_hollick(block.to_numpy(dtype=float), alpha, passes, reflect)
        baseflow_total += float(baseflow.sum())
        flow_total += float(block.sum())

    if flow_total <= 0:
        return np.nan
    return baseflow_total / flow_total


def _contiguous_blocks(q: pd.Series) -> list[pd.Series]:
    """Split a series at its gaps — both missing values and missing dates."""
    observed = q.dropna()
    if observed.empty:
        return []
    breaks = (observed.index.to_series().diff() > pd.Timedelta(days=1)).cumsum()
    return [block for _, block in observed.groupby(breaks)]


def _lyne_hollick(values: np.ndarray, alpha: float, passes: int, reflect: int) -> np.ndarray:
    """The filter itself, on a gap-free array, with reflected ends."""
    padded = np.concatenate([values[reflect:0:-1], values, values[-2:-reflect - 2:-1]])

    for pass_number in range(passes):
        series = padded if pass_number % 2 == 0 else padded[::-1]
        quick = np.zeros_like(series)
        for i in range(1, len(series)):
            quick[i] = alpha * quick[i - 1] + (1 + alpha) / 2 * (series[i] - series[i - 1])
        baseflow = np.where(quick > 0, series - quick, series)
        padded = baseflow if pass_number % 2 == 0 else baseflow[::-1]

    return padded[reflect:len(padded) - reflect + 1][:len(values)]


def flow_spell_stats(q: pd.Series, exceeded: pd.Series) -> tuple[float, float]:
    """Days per year spent in a flow spell, and the mean length of one.

    The rate is per day *observed*, rescaled to a year — not per complete water
    year. A year admitted at `min_coverage` is still short of days, and counting
    it as a whole one attributes the spells to a longer record than was actually
    measured, biasing every frequency low. Addor's reference implementation
    abandoned the per-year mean for exactly that reason.

    Spells are contiguous in the observed series, not in the calendar, so a gap
    joins the days on either side of it into one spell. That is the reference
    behaviour too, and it is why `duration` is the less trustworthy of the pair
    on a broken record.
    """
    if q.empty:
        return np.nan, np.nan

    spells = (exceeded != exceeded.shift()).cumsum()[exceeded]
    lengths = spells.groupby(spells).size()
    frequency = float(exceeded.sum() / len(q) * DAYS_PER_YEAR)
    duration = float(lengths.mean()) if len(lengths) else 0.0
    return frequency, duration


def high_flow_stats(q: pd.Series, factor: float = 9) -> tuple[float, float]:
    """Frequency (days/year) and mean duration of flows above `factor` x the median."""
    return flow_spell_stats(q, q > factor * q.median())


def low_flow_stats(q: pd.Series, factor: float = 0.2) -> tuple[float, float]:
    """Frequency (days/year) and mean duration of flows below `factor` x the mean."""
    return flow_spell_stats(q, q < factor * q.mean())


def half_flow_date(q: pd.Series, start_month: int) -> float:
    """Mean calendar day of year by which half the annual flow has passed.

    The centre of mass of the hydrograph, and the signature most likely to move
    as a glacierized catchment loses ice. Each water year contributes the date
    it crossed half of its total, but the mean is taken over the days *elapsed
    in the water year* and only then read back as a day of year: a catchment
    whose half-flow date sits near the new year would otherwise average a few
    Decembers and a few Januaries into the middle of the year.
    """
    years = water_year(q.index, start_month)

    elapsed = []
    for year, block in q.groupby(years):
        cumulative = block.cumsum()
        if cumulative.iloc[-1] <= 0:
            continue
        reached = cumulative >= cumulative.iloc[-1] / 2
        crossed = block.index[reached.to_numpy().argmax()]
        elapsed.append((crossed - pd.Timestamp(year=year, month=start_month, day=1)).days)

    if not elapsed:
        return np.nan
    start_doy = pd.Timestamp(year=2001, month=start_month, day=1).dayofyear   # a non-leap reference year
    return float((start_doy - 1 + np.mean(elapsed)) % 365 + 1)


def max_flow_doy(q: pd.Series, start_month: int, window: int) -> float:
    """Mean calendar day of year of the annual `window`-day flood peak."""
    return _extreme_flow_doy(q, start_month, window, np.argmax)


def min_flow_doy(q: pd.Series, start_month: int, window: int) -> float:
    """Mean calendar day of year of the annual `window`-day low flow."""
    return _extreme_flow_doy(q, start_month, window, np.argmin)


def _extreme_flow_doy(q: pd.Series, start_month: int, window: int, pick) -> float:
    """The date each water year reaches its `window`-day extreme, averaged around the year.

    The mean is taken over a centred rolling mean rather than over the daily
    series: a single-day spike is a gauging artefact as often as a flood, and
    the date of the lowest *week* is what a dry season is. The window is
    counted in calendar days, so a gap never becomes seven days of averaging
    spread over a month — a window holding an unobserved day yields nothing,
    and a water year with no complete window is skipped.
    """
    smoothed = q.asfreq("D").rolling(window, center=True, min_periods=window).mean()

    days = []
    for _, block in smoothed.groupby(water_year(smoothed.index, start_month)):
        observed = block.dropna()
        if not observed.empty:
            days.append(observed.index[pick(observed.to_numpy())].dayofyear)

    return _mean_day_of_year(days)


def _mean_day_of_year(days: list[int]) -> float:
    """The circular mean of a set of days of year.

    Circular because these dates are not on a line: two years peaking on 31
    December and 1 January are two days apart, and their arithmetic mean is the
    beginning of July. Dates spread exactly evenly around the year cancel to a
    resultant with no direction, which is NaN rather than an arbitrary day; a
    merely weakly clustered catchment still gets a date, and `seasonality` is
    the number that says how much to trust it. The turn of the year lands just
    below 1 rather than at 366, as it does in `seasonality`.
    """
    if not days:
        return np.nan

    angle = 2 * np.pi * np.asarray(days) / DAYS_PER_YEAR
    x, y = float(np.cos(angle).mean()), float(np.sin(angle).mean())
    if np.hypot(x, y) < 1e-9:
        return np.nan
    return float(np.arctan2(y, x) % (2 * np.pi) / (2 * np.pi) * DAYS_PER_YEAR)


def seasonality(q: pd.Series) -> tuple[float, float]:
    """Timing and strength of the annual flow cycle, by circular statistics.

    Each day is a vector on the year-circle weighted by that day's flow (Burn
    1997). Returns the calendar day of year the resultant points at — the mean
    flow date — and its length between 0 and 1: 0 is flow spread evenly over
    the year, 1 is every drop arriving on the same date.
    """
    if q.empty or q.sum() <= 0:
        return np.nan, np.nan

    angle = 2 * np.pi * q.index.dayofyear.to_numpy() / 365.25
    x = float((q.to_numpy() * np.cos(angle)).sum() / q.sum())
    y = float((q.to_numpy() * np.sin(angle)).sum() / q.sum())

    mean_day = float(np.degrees(np.arctan2(y, x)) % 360 / 360 * 365.25)
    strength = float(np.hypot(x, y))
    return mean_day, strength


def recession_constant(q: pd.Series, min_length: int = 5) -> float:
    """Linear-reservoir recession constant k (1/day), over declining spells.

    Median of -d(ln Q)/dt across every run of at least `min_length` consecutive
    declining days. Small k means a catchment that drains slowly — the storage
    time scale is 1/k days.
    """
    rates = []
    for block in _contiguous_blocks(q):
        positive = block[block > 0]
        if len(positive) < min_length + 1:
            continue

        log_q = np.log(positive.to_numpy(dtype=float))
        step = np.diff(log_q)
        declining = step < 0

        run_id = np.concatenate([[0], np.cumsum(declining[1:] != declining[:-1])])
        for run in np.unique(run_id[declining]):
            spell = step[declining & (run_id == run)]
            if len(spell) >= min_length:
                rates.append(-spell)

    if not rates:
        return np.nan
    return float(np.median(np.concatenate(rates)))


def signatures(q: pd.Series,
               p: pd.Series | None = None,
               start_month: int = 4,
               min_coverage: float = 0.9,
               min_years: int = 5,
               bfi_alpha: float = 0.925,
               bfi_passes: int = 3,
               high_flow_factor: float = 9,
               low_flow_factor: float = 0.2,
               fdc_percentiles: tuple[float, float] = (0.33, 0.66),
               rolling_window: int = 7,
               recession_min_length: int = 5) -> dict[str, float]:
    """Every signature for one gauge, over its complete water years.

    `q` is daily flow in mm/day and `p` the matching daily precipitation, also
    mm/day; without `p` the two forcing-dependent signatures are NaN. A record
    with fewer than `min_years` complete water years returns NaN for every
    signature.
    """
    complete = complete_water_years(q.dropna(), start_month, min_coverage)
    n_years = complete.groupby(water_year(complete.index, start_month)).ngroups

    if n_years < min_years:
        return {"sig_n_years": int(n_years)}

    high_freq, high_dur = high_flow_stats(complete, high_flow_factor)
    low_freq, low_dur = low_flow_stats(complete, low_flow_factor)
    mean_day, strength = seasonality(complete)

    return {"sig_n_years": int(n_years),
            "q_mean": q_mean(complete),
            "runoff_ratio": runoff_ratio(complete, p) if p is not None else np.nan,
            "stream_elas": stream_elasticity(complete, p, start_month, min_coverage) if p is not None else np.nan,
            "slope_fdc": slope_fdc(complete, *fdc_percentiles),
            "baseflow_index": baseflow_index(complete, bfi_alpha, bfi_passes),
            "q5": flow_percentile(complete, 0.05),
            "q95": flow_percentile(complete, 0.95),
            "high_q_freq": high_freq,
            "high_q_dur": high_dur,
            "low_q_freq": low_freq,
            "low_q_dur": low_dur,
            "hfd_mean": half_flow_date(complete, start_month),
            "q_max_doy": max_flow_doy(complete, start_month, rolling_window),
            "q_min_doy": min_flow_doy(complete, start_month, rolling_window),
            "q_centroid_doy": mean_day,
            "seasonality": strength,
            "recession_k": recession_constant(complete, recession_min_length)}

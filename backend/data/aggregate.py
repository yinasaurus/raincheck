"""Turn daily weather into weeks, months, and one row per growing season.

Planting-season weeks are counted from the first day of the season in blocks
of 7 local days. They are not ISO calendar weeks, so week 1 is the same
point in the crop calendar every year. A short final block (June-October is
153 days, so 21 full weeks and a 6-day tail) is kept for rainfall totals and
left out of the model so every scored week has the same length.
"""

from __future__ import annotations

import calendar
from datetime import date

import pandas as pd

DAILY_COLUMNS = [
    "date",
    "precipitation_mm",
    "temp_mean_c",
    "temp_max_c",
    "temp_min_c",
]


def assert_contiguous_season(months: list[int]) -> None:
    """Reject seasons that wrap past December.

    A November-March rice season needs a different year boundary. This
    prototype only supports one calendar year so the demo stays easy to check.
    """
    if not months:
        raise ValueError("planting_season_months cannot be empty")
    if any(month < 1 or month > 12 for month in months):
        raise ValueError(f"month out of range: {months}")
    expected = list(range(months[0], months[-1] + 1))
    if list(months) != expected:
        raise ValueError(
            "Planting season months must be contiguous inside one calendar year "
            f"(for example 6,7,8,9,10). Got {list(months)}."
        )


def season_bounds(year: int, months: list[int]) -> tuple[date, date]:
    assert_contiguous_season(months)
    start = date(year, months[0], 1)
    end = date(year, months[-1], calendar.monthrange(year, months[-1])[1])
    return start, end


def expected_season_days(year: int, months: list[int]) -> int:
    start, end = season_bounds(year, months)
    return (end - start).days + 1


def calendar_season_weeks(months: list[int]) -> int:
    """Full 7-day blocks in the season, using 2001 so a leap day cannot change the count.

    The default June-October window does not include February, so every year
    is the same length. A season that includes February can be one day longer
    in a leap year; that extra day stays in the partial tail and does not
    add a model week.
    """
    weeks = expected_season_days(2001, months) // 7
    if weeks < 2:
        raise ValueError("planting season is too short for week-of-season features")
    return weeks


def prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in DAILY_COLUMNS if column not in daily.columns]
    if missing:
        raise ValueError(f"daily frame is missing columns: {missing}")
    frame = daily.loc[:, DAILY_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    if frame["date"].duplicated().any():
        raise ValueError("daily frame has duplicate dates")
    for column in DAILY_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def _temperature_mean(values: pd.Series) -> float | None:
    observed = values.dropna()
    if observed.empty:
        return None
    return float(observed.mean())


def _temperature_extreme(values: pd.Series, how: str) -> float | None:
    observed = values.dropna()
    if observed.empty:
        return None
    return float(observed.max() if how == "max" else observed.min())


def aggregate_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Monday-start calendar weeks. Rainfall is summed. Temperatures are not filled in."""
    frame = prepare_daily(daily)
    columns = [
        "week_start",
        "week_end",
        "precipitation_mm",
        "temp_mean_c",
        "temp_max_c",
        "temp_min_c",
        "n_days",
        "precip_nulls",
        "missing_days",
        "partial",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame = frame.assign(week_start=frame["date"] - pd.to_timedelta(frame["date"].dt.weekday, unit="D"))
    rows: list[dict] = []
    for week_start, group in frame.groupby("week_start", sort=True):
        precip_nulls = int(group["precipitation_mm"].isna().sum())
        n_days = int(len(group))
        missing_days = 7 - n_days
        precip = group["precipitation_mm"].sum(min_count=1)
        rows.append(
            {
                "week_start": pd.Timestamp(week_start).date().isoformat(),
                "week_end": (pd.Timestamp(week_start) + pd.Timedelta(days=6)).date().isoformat(),
                "precipitation_mm": None if pd.isna(precip) else float(precip),
                "temp_mean_c": _temperature_mean(group["temp_mean_c"]),
                "temp_max_c": _temperature_extreme(group["temp_max_c"], "max"),
                "temp_min_c": _temperature_extreme(group["temp_min_c"], "min"),
                "n_days": n_days,
                "precip_nulls": precip_nulls,
                "missing_days": missing_days,
                "partial": missing_days > 0 or precip_nulls > 0,
            }
        )
    return pd.DataFrame(rows)


def aggregate_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_daily(daily)
    columns = [
        "month_start",
        "year",
        "month",
        "precipitation_mm",
        "temp_mean_c",
        "temp_max_c",
        "temp_min_c",
        "n_days",
        "expected_days",
        "precip_nulls",
        "missing_days",
        "partial",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    frame = frame.assign(
        month_start=frame["date"].dt.to_period("M").dt.to_timestamp(),
        year=frame["date"].dt.year,
        month=frame["date"].dt.month,
    )
    rows: list[dict] = []
    for month_start, group in frame.groupby("month_start", sort=True):
        year = int(group["year"].iloc[0])
        month = int(group["month"].iloc[0])
        expected = calendar.monthrange(year, month)[1]
        n_days = int(len(group))
        precip_nulls = int(group["precipitation_mm"].isna().sum())
        precip = group["precipitation_mm"].sum(min_count=1)
        rows.append(
            {
                "month_start": pd.Timestamp(month_start).date().isoformat(),
                "year": year,
                "month": month,
                "precipitation_mm": None if pd.isna(precip) else float(precip),
                "temp_mean_c": _temperature_mean(group["temp_mean_c"]),
                "temp_max_c": _temperature_extreme(group["temp_max_c"], "max"),
                "temp_min_c": _temperature_extreme(group["temp_min_c"], "min"),
                "n_days": n_days,
                "expected_days": expected,
                "precip_nulls": precip_nulls,
                "missing_days": expected - n_days,
                "partial": n_days < expected or precip_nulls > 0,
            }
        )
    return pd.DataFrame(rows)


def season_totals(daily: pd.DataFrame, months: list[int]) -> pd.DataFrame:
    """One row per year that has at least one day inside the planting season."""
    frame = prepare_daily(daily)
    columns = [
        "year",
        "start",
        "end",
        "rainfall_mm",
        "temp_mean_c",
        "temp_max_c",
        "n_days",
        "precip_obs_days",
        "expected_days",
        "hot_days",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict] = []
    for year in sorted(frame["date"].dt.year.unique()):
        start, end = season_bounds(int(year), months)
        mask = (frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))
        group = frame.loc[mask]
        if group.empty:
            continue
        precip = group["precipitation_mm"].sum(min_count=1)
        rows.append(
            {
                "year": int(year),
                "start": start.isoformat(),
                "end": end.isoformat(),
                "rainfall_mm": None if pd.isna(precip) else float(precip),
                "temp_mean_c": _temperature_mean(group["temp_mean_c"]),
                "temp_max_c": _temperature_extreme(group["temp_max_c"], "max"),
                "n_days": int(len(group)),
                "precip_obs_days": int(group["precipitation_mm"].notna().sum()),
                "expected_days": expected_season_days(int(year), months),
                "hot_days": None,
            }
        )
    return pd.DataFrame(rows)


def season_week_buckets(
    daily: pd.DataFrame,
    year: int,
    months: list[int],
    heat_day_celsius: float,
) -> pd.DataFrame:
    """Cover every local day of one season exactly once, in 7-day blocks."""
    frame = prepare_daily(daily)
    start, end = season_bounds(year, months)
    columns = [
        "year",
        "week_index",
        "week_start",
        "week_end",
        "n_days",
        "observed_days",
        "partial",
        "precipitation_mm",
        "precip_nulls",
        "temp_mean_sum_c",
        "temp_obs_days",
        "temp_max_c",
        "hot_days",
    ]
    window = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))].copy()
    if window.empty:
        return pd.DataFrame(columns=columns)

    by_date = window.set_index("date")
    rows: list[dict] = []
    cursor = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    week_index = 1
    while cursor <= end_ts:
        week_end = min(cursor + pd.Timedelta(days=6), end_ts)
        days = pd.date_range(cursor, week_end, freq="D")
        present = by_date.reindex(days)
        precip_nulls = int(present["precipitation_mm"].isna().sum())
        precip = present["precipitation_mm"].sum(min_count=1)
        temp_obs = present["temp_mean_c"].dropna()
        hot = present["temp_max_c"].dropna()
        calendar_days = int(len(days))
        # A week used by the model has to be a full 7 days with rain and temperature.
        # The short tail after the last full week stays in the table for the
        # season rainfall total, and is marked partial so the model skips it.
        partial = calendar_days < 7 or precip_nulls > 0 or len(temp_obs) < calendar_days or len(hot) < calendar_days
        rows.append(
            {
                "year": year,
                "week_index": week_index,
                "week_start": cursor.date().isoformat(),
                "week_end": week_end.date().isoformat(),
                "n_days": calendar_days,
                "observed_days": int(present["precipitation_mm"].notna().sum()),
                "partial": partial,
                "precipitation_mm": None if pd.isna(precip) else float(precip),
                "precip_nulls": precip_nulls,
                "temp_mean_sum_c": None if temp_obs.empty else float(temp_obs.sum()),
                "temp_obs_days": int(len(temp_obs)),
                "temp_max_c": None if hot.empty else float(hot.max()),
                "hot_days": int((hot >= heat_day_celsius).sum()),
            }
        )
        week_index += 1
        cursor = week_end + pd.Timedelta(days=1)
    return pd.DataFrame(rows)

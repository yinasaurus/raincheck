"""Aggregation: sums must match the daily input, and short weeks stay marked."""

from datetime import date, timedelta

import pandas as pd
import pytest

from data.aggregate import (
    aggregate_monthly,
    aggregate_weekly,
    calendar_season_weeks,
    expected_season_days,
    prepare_daily,
    season_totals,
    season_week_buckets,
    assert_contiguous_season,
)


def _daily(start: date, days: int, rain: float = 1.0, temp: float = 28.0, hot: float = 33.0) -> pd.DataFrame:
    rows = []
    for offset in range(days):
        current = start + timedelta(days=offset)
        rows.append(
            {
                "date": current.isoformat(),
                "precipitation_mm": rain,
                "temp_mean_c": temp,
                "temp_max_c": hot,
                "temp_min_c": temp - 5,
            }
        )
    return pd.DataFrame(rows)


def test_weekly_rainfall_sums_back_to_the_daily_total():
    frame = _daily(date(2021, 6, 1), 10, rain=1.5)
    weekly = aggregate_weekly(frame)
    assert weekly["precipitation_mm"].sum() == pytest.approx(15.0)
    assert weekly["partial"].all()
    assert int(weekly["n_days"].sum()) == 10


def test_monthly_rainfall_and_partial_flag():
    frame = _daily(date(2021, 6, 1), 10, rain=2)
    monthly = aggregate_monthly(frame)
    assert len(monthly) == 1
    assert monthly.iloc[0]["precipitation_mm"] == pytest.approx(20)
    assert monthly.iloc[0]["month"] == 6
    assert bool(monthly.iloc[0]["partial"])
    assert int(monthly.iloc[0]["expected_days"]) == 30
    assert int(monthly.iloc[0]["missing_days"]) == 20


def test_duplicate_dates_are_rejected():
    frame = _daily(date(2021, 6, 1), 2)
    doubled = pd.concat([frame, frame], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        prepare_daily(doubled)


def test_june_to_october_is_153_days_and_21_model_weeks():
    assert expected_season_days(2021, [6, 7, 8, 9, 10]) == 153
    assert expected_season_days(2024, [6, 7, 8, 9, 10]) == 153
    assert calendar_season_weeks([6, 7, 8, 9, 10]) == 21


def test_season_buckets_cover_every_day_once_and_mark_the_tail():
    frame = _daily(date(2021, 6, 1), 30, rain=1)
    buckets = season_week_buckets(frame, 2021, [6], heat_day_celsius=35)
    assert int(buckets["n_days"].sum()) == 30
    assert buckets["precipitation_mm"].sum() == pytest.approx(30)
    assert buckets["partial"].tolist() == [False, False, False, False, True]
    assert int(buckets.iloc[-1]["n_days"]) == 2


def test_season_total_matches_daily_rainfall():
    frame = _daily(date(2021, 6, 1), 30, rain=3)
    totals = season_totals(frame, [6])
    assert int(totals.iloc[0]["year"]) == 2021
    assert totals.iloc[0]["rainfall_mm"] == pytest.approx(90)
    assert int(totals.iloc[0]["expected_days"]) == 30


def test_cross_year_season_is_rejected():
    with pytest.raises(ValueError, match="contiguous"):
        assert_contiguous_season([11, 12, 1])

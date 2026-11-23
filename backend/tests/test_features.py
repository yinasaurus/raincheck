"""Percent-of-normal leaves out the year being scored."""

import pandas as pd
import pytest

from ml.baseline import baseline_calls_drought, baseline_probability
from ml.features import build_feature_frame


def _buckets(year: int, weekly_rain: list[float]) -> pd.DataFrame:
    rows = []
    for index, rain in enumerate(weekly_rain, start=1):
        rows.append(
            {
                "year": year,
                "week_index": index,
                "week_start": f"{year}-06-{index:02d}",
                "week_end": f"{year}-06-{index + 7:02d}",
                "n_days": 7,
                "observed_days": 7,
                "partial": False,
                "precipitation_mm": rain,
                "precip_nulls": 0,
                "temp_mean_sum_c": 28 * 7,
                "temp_obs_days": 7,
                "temp_max_c": 34.0,
                "hot_days": 1,
            }
        )
    rows.append(
        {
            "year": year,
            "week_index": len(weekly_rain) + 1,
            "week_start": f"{year}-07-01",
            "week_end": f"{year}-07-06",
            "n_days": 6,
            "observed_days": 6,
            "partial": True,
            "precipitation_mm": 5.0,
            "precip_nulls": 0,
            "temp_mean_sum_c": 28 * 6,
            "temp_obs_days": 6,
            "temp_max_c": 34.0,
            "hot_days": 0,
        }
    )
    return pd.DataFrame(rows)


def test_leave_one_year_out_normal_and_tail_is_not_a_feature_row():
    buckets = {
        2001: _buckets(2001, [10, 10]),
        2002: _buckets(2002, [10, 10]),
        2003: _buckets(2003, [0, 0]),
    }
    labels = {2001: False, 2002: False, 2003: True}
    frame = build_feature_frame(buckets, [2001, 2002, 2003], [2001, 2002, 2003], labels, season_weeks=2)
    dry = frame[(frame["year"] == 2003) & (frame["week_index"] == 1)].iloc[0]
    assert dry["cumulative_rainfall_mm"] == 0
    assert dry["normal_cumulative_mm"] == 10
    assert dry["cumulative_pct_of_normal"] == 0
    wet = frame[(frame["year"] == 2001) & (frame["week_index"] == 1)].iloc[0]
    # 2001 is compared with 2002 (10 mm) and 2003 (0 mm), not with itself.
    assert wet["normal_cumulative_mm"] == 5
    assert wet["cumulative_pct_of_normal"] == 2
    later = frame[(frame["year"] == 2003) & (frame["week_index"] == 2)].iloc[0]
    assert later["rainfall_trend_mm"] == 0
    assert later["cumulative_rainfall_mm"] == 0
    assert frame["week_index"].max() == 2


def test_a_broken_middle_week_stops_the_feature_weeks():
    broken = _buckets(2004, [10, 10, 10])
    broken.loc[broken["week_index"] == 2, "partial"] = True
    buckets = {
        2001: _buckets(2001, [10, 10, 10]),
        2002: _buckets(2002, [10, 10, 10]),
        2003: _buckets(2003, [10, 10, 10]),
        2004: broken,
    }
    labels = {2001: False, 2002: False, 2003: False, 2004: False}
    frame = build_feature_frame(buckets, [2004], [2001, 2002, 2003, 2004], labels, season_weeks=3)
    assert frame["week_index"].tolist() == [1]


def test_baseline_calls_drought_only_under_75_percent_of_normal():
    assert bool(baseline_calls_drought([0.749])[0])
    assert not bool(baseline_calls_drought([0.75])[0])
    probability = baseline_probability([1.0, 0.75, 0.5])
    assert probability[0] == pytest.approx(0.15)
    assert probability[1] == pytest.approx(0.50)
    assert probability[2] == pytest.approx(0.85)

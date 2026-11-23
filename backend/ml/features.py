"""Week-of-season features. Normals leave out the year being scored.

If the year being scored is part of the reference set, its own rainfall is
removed before the average is taken. A held-out year uses only the training
years. That keeps "percent of normal" from containing the answer we are scoring.

Weeks are aligned from the first day of the season. Only a contiguous run of
complete 7-day weeks from week 1 is used. One short or broken year does not
truncate the other years; each week is averaged over the reference years that
actually have that week.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from data.aggregate import season_week_buckets

FEATURE_COLUMNS = [
    "fraction_elapsed",
    "cumulative_rainfall_mm",
    "cumulative_pct_of_normal",
    "recent_rainfall_mm",
    "recent_vs_normal",
    "rainfall_trend_mm",
    "temp_mean_to_date",
    "temp_max_to_date",
    "hot_days_to_date",
]

# A week whose usual rainfall is under 1 mm has no stable ratio.
MIN_NORMAL_WEEK_MM = 1.0


def buckets_for_years(
    daily: pd.DataFrame,
    years: list[int],
    months: list[int],
    heat_day_celsius: float,
) -> dict[int, pd.DataFrame]:
    return {year: season_week_buckets(daily, year, months, heat_day_celsius) for year in years}


def build_feature_frame(
    buckets_by_year: dict[int, pd.DataFrame],
    include_years: list[int],
    normal_years: list[int],
    label_by_year: dict[int, bool],
    season_weeks: int,
) -> pd.DataFrame:
    """One row per full week. The short tail week is not included."""
    curves = {}
    for year, buckets in buckets_by_year.items():
        curve = _contiguous_full_weeks(buckets)
        if curve is not None:
            curves[year] = curve

    rows: list[dict] = []
    for year in include_years:
        if year not in curves:
            continue
        reference = [other for other in normal_years if other != year and other in curves]
        if not reference:
            raise ValueError(f"no other season left to score {year}")
        curve = curves[year]
        width = len(curve["precip"])
        cumulative = np.cumsum(curve["precip"])
        temp_sum = np.cumsum(curve["temp_sum"])
        temp_days = np.cumsum(curve["temp_days"])
        hot = np.cumsum(curve["hot"])
        running_max = np.maximum.accumulate(curve["temp_max"])
        for index in range(width):
            peers = [curves[other] for other in reference if len(curves[other]["precip"]) > index]
            if not peers:
                break
            normal_to_date = float(np.mean([peer["cum"][index] for peer in peers]))
            normal_week = float(np.mean([peer["precip"][index] for peer in peers]))
            recent = float(curve["precip"][index])
            if normal_week < MIN_NORMAL_WEEK_MM:
                recent_vs_normal = 1.0
            else:
                recent_vs_normal = recent / normal_week
            trend = 0.0 if index == 0 else recent - float(curve["precip"][index - 1])
            week_number = index + 1
            rows.append(
                {
                    "year": year,
                    "week_index": week_number,
                    "week_start": curve["week_start"][index],
                    "week_end": curve["week_end"][index],
                    "fraction_elapsed": week_number / season_weeks,
                    "cumulative_rainfall_mm": float(cumulative[index]),
                    "normal_cumulative_mm": normal_to_date,
                    "cumulative_pct_of_normal": (
                        float(cumulative[index] / normal_to_date) if normal_to_date > 0 else np.nan
                    ),
                    "recent_rainfall_mm": recent,
                    "recent_vs_normal": recent_vs_normal,
                    "rainfall_trend_mm": trend,
                    "temp_mean_to_date": float(temp_sum[index] / temp_days[index]),
                    "temp_max_to_date": float(running_max[index]),
                    "hot_days_to_date": int(hot[index]),
                    "drought_stress": label_by_year[year] if year in label_by_year else None,
                    "aligned_weeks": width,
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.dropna(subset=FEATURE_COLUMNS).reset_index(drop=True)


def _contiguous_full_weeks(buckets: pd.DataFrame) -> dict | None:
    """Keep week 1, week 2, ... until the first week that is not a full 7 days."""
    if buckets is None or buckets.empty:
        return None
    kept: list[pd.Series] = []
    expected = 1
    for _, row in buckets.sort_values("week_index").iterrows():
        if int(row["week_index"]) != expected:
            break
        if bool(row["partial"]) or int(row["n_days"]) != 7 or pd.isna(row["precipitation_mm"]):
            break
        if int(row["temp_obs_days"]) < 7 or pd.isna(row["temp_max_c"]) or pd.isna(row["temp_mean_sum_c"]):
            break
        kept.append(row)
        expected += 1
    if not kept:
        return None
    precip = np.array([float(row["precipitation_mm"]) for row in kept])
    return {
        "precip": precip,
        "cum": np.cumsum(precip),
        "temp_sum": np.array([float(row["temp_mean_sum_c"]) for row in kept]),
        "temp_days": np.array([float(row["temp_obs_days"]) for row in kept]),
        "temp_max": np.array([float(row["temp_max_c"]) for row in kept]),
        "hot": np.array([float(row["hot_days"]) for row in kept]),
        "week_start": [row["week_start"] for row in kept],
        "week_end": [row["week_end"] for row in kept],
    }

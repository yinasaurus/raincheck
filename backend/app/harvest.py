"""Provincial rice harvest beside each rainfall season. A comparison only.

The harvest never reaches the payment line, the oracle, or the schedule.
Yields rise over the years, so each season is compared to a straight-line
trend fitted to the wet-season yields rather than to a flat average.
"""

from __future__ import annotations

import json
from pathlib import Path

from validation.analyze import deviation_percent


def load_harvest(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def wet_season_yields(harvest: dict | None) -> dict[int, float]:
    if not harvest:
        return {}
    found = {}
    for year, periods in (harvest.get("seasons") or {}).items():
        value = ((periods.get("wet_season") or {}).get("all") or {}).get("yield_t_per_ha")
        if value is not None:
            found[int(year)] = float(value)
    return found


def trend_line(yields: dict[int, float]) -> tuple[float, float] | None:
    """Least-squares slope and intercept, in tonnes per hectare per year."""
    if len(yields) < 3:
        return None
    years = list(yields)
    mean_year = sum(years) / len(years)
    mean_yield = sum(yields.values()) / len(yields)
    spread = sum((year - mean_year) ** 2 for year in years)
    if spread == 0:
        return None
    slope = sum((year - mean_year) * (yields[year] - mean_yield) for year in years) / spread
    return slope, mean_yield - slope * mean_year


def harvest_rows(harvest: dict | None) -> dict[int, dict]:
    """Per season: the yield and whole-percent difference from the trend."""
    yields = wet_season_yields(harvest)
    line = trend_line(yields)
    rows = {}
    for year, value in yields.items():
        vs_trend = None
        if line is not None:
            vs_trend = deviation_percent(value, line[0] * year + line[1])
        rows[year] = {"yield_t_per_ha": value, "vs_trend_pct": vs_trend}
    return rows


def harvest_summary(harvest: dict | None) -> dict | None:
    if not harvest:
        return None
    line = trend_line(wet_season_yields(harvest))
    return {
        "source": harvest.get("source"),
        "province": harvest.get("province"),
        "fetched_at": harvest.get("fetched_at"),
        "tables": harvest.get("tables"),
        "wet_season_note": harvest.get("wet_season_note"),
        "scope_note": harvest.get("scope_note"),
        "trend_t_per_ha_per_year": None if line is None else round(line[0], 3),
    }

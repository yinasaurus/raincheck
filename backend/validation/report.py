"""Build the harvest-check payload from rainfall seasons and the saved yield file."""

from __future__ import annotations

from app.harvest import trend_line, wet_season_yields
from validation.analyze import (
    SOURCE_NAME,
    SOURCE_URL,
    below_line_is_lower,
    bootstrap_spearman,
    deviation_percent,
    headline,
    limitations,
    median,
    verdict,
    worst_years,
)

DRY_YEARS = (2003, 2004, 2017)


def build_validation(rainfall_rows: list[dict], harvest: dict | None) -> dict:
    yields = wet_season_yields(harvest)
    line = trend_line(yields)
    series = []
    for row in sorted(rainfall_rows, key=lambda item: int(item["year"])):
        year = int(row["year"])
        deviation = None
        if line is not None and year in yields:
            deviation = deviation_percent(yields[year], line[0] * year + line[1])
        series.append(
            {
                "year": year,
                "season_rainfall_mm": row.get("season_total_mm"),
                "below_line": bool(row.get("relief_fired")),
                "yield_deviation_pct": deviation,
            }
        )
    paired = [row for row in series if row["yield_deviation_pct"] is not None and row["season_rainfall_mm"] is not None]
    dry = [row["yield_deviation_pct"] for row in paired if row["below_line"]]
    others = [row["yield_deviation_pct"] for row in paired if not row["below_line"]]
    correlation = bootstrap_spearman(
        [float(row["season_rainfall_mm"]) for row in paired],
        [float(row["yield_deviation_pct"]) for row in paired],
    )
    dry_lower = below_line_is_lower(dry, others)
    excludes_zero = bool(correlation and correlation["excludes_zero"])
    code = verdict(dry_lower, excludes_zero)
    covered = sorted(yields)
    worst = worst_years(series)
    worst_ids = {row["year"] for row in worst}
    for row in series:
        row["worst_yield"] = row["year"] in worst_ids
    return {
        "source_name": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "retrieval_date": None if not harvest else str(harvest.get("fetched_at") or "")[:10] or None,
        "retrieval_note": (
            "PalayStat publishes the Philippine Statistics Authority Palay Production Survey. "
            "These Nueva Ecija figures were downloaded from that survey's OpenSTAT tables."
        ),
        "years_covered": None
        if not covered
        else {"first": covered[0], "last": covered[-1]},
        "n": len(paired),
        "series": series,
        "spearman": correlation,
        "below_line_years": {
            "years": {str(year): _deviation_for(series, year) for year in DRY_YEARS},
            "other_years_median": None if median(others) is None else round(median(others), 1),
            "dry_years_median": None if median(dry) is None else round(median(dry), 1),
            "dry_years_below_other_median": dry_lower,
        },
        "worst_yield_years": [
            {
                "year": row["year"],
                "yield_deviation_pct": row["yield_deviation_pct"],
                "season_rainfall_mm": row["season_rainfall_mm"],
                "below_line": row["below_line"],
            }
            for row in worst
        ],
        "sample_size_warning": limitations(len(paired), sum(1 for row in paired if row["below_line"]))[0],
        "limitations": limitations(len(paired), sum(1 for row in paired if row["below_line"])),
        "validation": code,
        "headline": headline(code),
    }


def _deviation_for(series: list[dict], year: int):
    for row in series:
        if row["year"] == year:
            return row["yield_deviation_pct"]
    return None

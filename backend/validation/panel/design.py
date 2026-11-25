"""Fold rules locked on 25 Nov 2026 at 15:46, before any model fit.

A test row never supplies its own normal or its own yield line.
"""

from __future__ import annotations

CUTOFF_YEAR = 2007
MIN_EARLY_YEARS = 8
THRESHOLDS = (0.70, 0.75, 0.80, 0.85)


def line_fit(years: list[float], values: list[float]) -> tuple[float, float] | None:
    """Straight line value = intercept + slope * year. Needs two distinct years."""
    if len(years) < 2 or len(years) != len(values):
        return None
    x_mean = sum(years) / len(years)
    y_mean = sum(values) / len(values)
    var = sum((x - x_mean) ** 2 for x in years)
    if var == 0:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(years, values)) / var
    return y_mean - slope * x_mean, slope


def fitted_value(intercept: float, slope: float, year: float) -> float:
    return intercept + slope * year


def deviation_percent(actual: float, expected: float) -> float | None:
    """Percent gap from the frozen line. None when the line is not a positive yield."""
    if expected <= 0:
        return None
    return (actual / expected - 1.0) * 100.0


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _complete(row: dict) -> bool:
    return (
        row.get("yield_kg_ha") is not None
        and row.get("season_mm") is not None
        and row.get("dry2_mm") is not None
        and row.get("irrig_share") is not None
        and row["season_mm"] >= 0
        and row["dry2_mm"] >= 0
    )


def _baseline(early: list[dict]) -> dict | None:
    if len(early) < MIN_EARLY_YEARS:
        return None
    line = line_fit([r["year"] for r in early], [r["yield_kg_ha"] for r in early])
    if line is None:
        return None
    season_norm = mean([r["season_mm"] for r in early])
    dry_norm = mean([r["dry2_mm"] for r in early])
    shares = [r["irrig_share"] for r in early]
    if season_norm is None or season_norm <= 0 or dry_norm is None or dry_norm <= 0:
        return None
    return {
        "intercept": line[0],
        "slope": line[1],
        "season_norm": season_norm,
        "dry_norm": dry_norm,
        "irrig_median": sorted(shares)[len(shares) // 2] if len(shares) % 2 else (
            sorted(shares)[len(shares) // 2 - 1] + sorted(shares)[len(shares) // 2]
        ) / 2,
    }


def _pack(row: dict, base: dict) -> dict | None:
    expected = fitted_value(base["intercept"], base["slope"], row["year"])
    gap = deviation_percent(row["yield_kg_ha"], expected)
    if gap is None:
        return None
    season_pct = row["season_mm"] / base["season_norm"]
    dry_pct = row["dry2_mm"] / base["dry_norm"]
    return {
        "district_id": row["district_id"],
        "state": row["state"],
        "year": row["year"],
        "name": row.get("name"),
        "gap": gap,
        "loss_10": gap <= -10.0,
        "loss_5": gap <= -5.0,
        "loss_15": gap <= -15.0,
        "season_pct": season_pct,
        "dry_pct": dry_pct,
        "irrig_share": row["irrig_share"],
        "irrig_median": base["irrig_median"],
        "interact": season_pct * row["irrig_share"],
    }


def _grouped(rows: list[dict]) -> dict:
    grouped: dict = {}
    for row in rows:
        if _complete(row):
            grouped.setdefault(row["district_id"], []).append(row)
    return grouped


def baselines(rows: list[dict], cutoff: int = CUTOFF_YEAR) -> dict:
    found = {}
    for district, items in _grouped(rows).items():
        early = [r for r in items if r["year"] <= cutoff]
        base = _baseline(early)
        if base is not None:
            found[district] = base
    return found


def temporal_fold(rows: list[dict], cutoff: int = CUTOFF_YEAR) -> tuple[list[dict], list[dict]]:
    """Train on years through the cutoff. Test on later years. Normals use the early years only."""
    bases = baselines(rows, cutoff)
    train: list[dict] = []
    test: list[dict] = []
    for row in rows:
        if not _complete(row) or row["district_id"] not in bases:
            continue
        packed = _pack(row, bases[row["district_id"]])
        if packed is None:
            continue
        if row["year"] <= cutoff:
            train.append(packed)
        else:
            test.append(packed)
    return train, test


def spatial_fold(rows: list[dict], held_out: str, cutoff: int = CUTOFF_YEAR) -> tuple[list[dict], list[dict]]:
    """Hold one state out of the classifier.

    That state's early years set its normal and its yield line, and are not
    training rows or test rows. Its later years are the test.
    """
    bases = baselines(rows, cutoff)
    train: list[dict] = []
    test: list[dict] = []
    for row in rows:
        if not _complete(row) or row["district_id"] not in bases:
            continue
        packed = _pack(row, bases[row["district_id"]])
        if packed is None:
            continue
        if row["state"] == held_out:
            if row["year"] > cutoff:
                test.append(packed)
        elif row["year"] <= cutoff:
            train.append(packed)
    return train, test


def tertile_cuts(train_rows: list[dict]) -> tuple[float, float] | None:
    """Cuts from each training district's early-year median share."""
    by_district: dict = {}
    for row in train_rows:
        by_district.setdefault(row["district_id"], row["irrig_median"])
    shares = sorted(by_district.values())
    if len(shares) < 3:
        return None
    def at(fraction: float) -> float:
        pos = (len(shares) - 1) * fraction
        low = int(pos)
        high = min(low + 1, len(shares) - 1)
        weight = pos - low
        return shares[low] * (1 - weight) + shares[high] * weight
    return at(1 / 3), at(2 / 3)


def tertile(share: float, cuts: tuple[float, float] | None) -> str | None:
    if cuts is None:
        return None
    low, high = cuts
    if share <= low:
        return "low"
    if share <= high:
        return "mid"
    return "high"

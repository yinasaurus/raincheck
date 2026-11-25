"""Compare provincial rice yield with the rainfall seasons. Pure functions only.

The result is a comparison. It is never an input to the model, the oracle,
the payment line, or a decision to change a payment.
"""

from __future__ import annotations

import random

SOURCE_NAME = "PhilRice PalayStat"
SOURCE_URL = "https://palaystat.philrice.gov.ph/"

SUPPORTS = "SUPPORTS"
MIXED = "MIXED"
WEAK = "WEAK"
OPPOSITE = "OPPOSITE"

# v1 did not look at the sign. Kept so the original output can be shown beside v2.
ORIGINAL_HEADLINES = {
    SUPPORTS: "Past harvest records for this province lined up with the dry seasons in the data.",
    MIXED: "Past harvest records for this province only partly lined up with the dry seasons in the data.",
    WEAK: "Past harvest records for this province did not line up with the dry seasons in the data.",
}

HEADLINES = {
    SUPPORTS: (
        "In past harvest records for this province, the seasons below the payment line had lower yields, "
        "and wetter seasons tended to have higher yields."
    ),
    MIXED: (
        "In past harvest records for this province, the two harvest checks do not agree. "
        "This rainfall line is not a proven predictor of yield loss here."
    ),
    WEAK: (
        "In past harvest records for this province, the seasons below the payment line did not have lower yields, "
        "and this sample does not show a clear link between rainfall and yield."
    ),
    OPPOSITE: (
        "In past harvest records for this province, the seasons below the payment line did not have lower yields, "
        "and wetter seasons tended to have lower yields. "
        "This rainfall line is not a proven predictor of yield loss here."
    ),
}

BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_SEED = 1363


def deviation_percent(actual: float, expected: float) -> int | None:
    """Whole-percent gap from the trend. None when the trend is not a positive yield."""
    if expected <= 0:
        return None
    return round((actual / expected - 1) * 100)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def _ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[start][1]:
            end += 1
        # Ranks are 1-based. Ties share the average rank.
        shared = (start + 1 + end + 1) / 2
        for cursor in range(start, end + 1):
            ranks[ordered[cursor][0]] = shared
        start = end + 1
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    count = len(left)
    if count < 3 or count != len(right):
        return None
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    spread_left = sum((value - mean_left) ** 2 for value in left)
    spread_right = sum((value - mean_right) ** 2 for value in right)
    if spread_left == 0 or spread_right == 0:
        return None
    paired = sum((left[i] - mean_left) * (right[i] - mean_right) for i in range(count))
    return paired / (spread_left ** 0.5 * spread_right ** 0.5)


def spearman(rainfall: list[float], deviation: list[float]) -> float | None:
    if len(rainfall) < 3 or len(rainfall) != len(deviation):
        return None
    return _pearson(_ranks(rainfall), _ranks(deviation))


def _percentile(ordered: list[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_spearman(
    rainfall: list[float],
    deviation: list[float],
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict | None:
    """Percentile interval from resampling whole years. None when a correlation cannot be computed."""
    observed = spearman(rainfall, deviation)
    if observed is None:
        return None
    count = len(rainfall)
    picker = random.Random(seed)
    samples: list[float] = []
    for _ in range(draws):
        picked = [picker.randrange(count) for _ in range(count)]
        value = spearman([rainfall[i] for i in picked], [deviation[i] for i in picked])
        if value is not None:
            samples.append(value)
    if not samples:
        return None
    samples.sort()
    low = _percentile(samples, 0.025)
    high = _percentile(samples, 0.975)
    return {
        "correlation": round(observed, 3),
        "interval_low": round(low, 3),
        "interval_high": round(high, 3),
        "draws": draws,
        "excludes_zero": low > 0 or high < 0,
    }


def below_line_is_lower(below: list[float], others: list[float]) -> bool:
    """True when the dry seasons' median deviation is under the median of the other seasons."""
    dry = median(below)
    rest = median(others)
    if dry is None or rest is None:
        return False
    return dry < rest


def verdict(dry_years_are_lower: bool, interval_excludes_zero: bool) -> str:
    """v1, sign-blind. SUPPORTS needs both checks. MIXED is exactly one. WEAK is neither."""
    if dry_years_are_lower and interval_excludes_zero:
        return SUPPORTS
    if dry_years_are_lower or interval_excludes_zero:
        return MIXED
    return WEAK


def verdict_v2(dry_years_are_lower: bool, correlation: float | None, interval_excludes_zero: bool) -> str:
    """v2 reads the sign. A negative link plus dry years that are not lower is OPPOSITE."""
    negative = bool(interval_excludes_zero and correlation is not None and correlation < 0)
    positive = bool(interval_excludes_zero and correlation is not None and correlation > 0)
    if (not dry_years_are_lower) and negative:
        return OPPOSITE
    if dry_years_are_lower and positive:
        return SUPPORTS
    if dry_years_are_lower or positive or negative:
        return MIXED
    return WEAK


def headline(code: str) -> str:
    return HEADLINES[code]


def worst_years(rows: list[dict], count: int = 5) -> list[dict]:
    """The lowest yield deviations. Rows without a deviation are left out."""
    ranked = [row for row in rows if row.get("yield_deviation_pct") is not None]
    ranked.sort(key=lambda row: (row["yield_deviation_pct"], row["year"]))
    return ranked[:count]


def limitations(paired: int, dry: int) -> list[str]:
    return [
        f"The sample is small: {paired} seasons have a harvest, and {dry} of them finished below the payment line.",
        "A typhoon can cut a harvest in a year that was not dry.",
        "Pests and disease can cut a harvest with no change in the season's rainfall.",
        "Seeds and varieties changed over these years, and newer varieties yield more.",
        "Most Nueva Ecija rice is irrigated, so a dry spell at one map point may not change the provincial harvest.",
        "Prices and how much land is planted change the harvest as well as the weather.",
        "The harvest figure is the July to December crop. The rainfall season is June to October, so the two calendars do not match exactly.",
        "This comparison does not change the payment line, the model, or the trigger.",
    ]

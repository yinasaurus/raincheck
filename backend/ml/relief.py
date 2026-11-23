"""Chance that the season total finishes below the payment line.

The target is P(June-October rainfall ends strictly below 1,363.0 mm | rain
observed through week w). That is the contract's decision, in tenths of a
millimetre (13,630). It is not the SPI drought label.

Only 3 of the 26 seasons on this cache end below the line (2003, 2004, 2017).
Metrics on 26 seasons will move if one year is added or removed. Bootstrap
intervals describe this sample. They are not a significance test.

Selection rule, fixed before any per-year inspection:

    Choose the candidate with the lowest mean Brier score across weeks
    4, 8, 12, 16 and 21. If two means are within 0.005, pick the simpler
    candidate. Simplicity, simplest first: rule, logistic, analog_raw,
    analog_scaled, lognormal, gamma, v1_no_temp, v1.

    Lead time, false alarms, calibration, and per-year plots are not
    allowed to break a tie.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from ml.baseline import baseline_probability

# 1,363.0 mm in the contract's unit. Relief fires only when the total is strictly below.
PAYMENT_LINE_TENTHS = 13630
PAYMENT_LINE_MM = 1363.0
CHECKPOINTS = (4, 8, 12, 16, 21)
N_SCORED_WEEKS = 21
# Only three seasons on this record finish under the line. Say so wherever a metric is shown.
N_POSITIVE_SEASONS_NOTE = (
    "Only 3 of 26 seasons ended below the 1,363.0 mm payment line. "
    "Averages, bootstrap intervals, and the calibration table describe this sample. "
    "They are not a test of statistical significance."
)
TIE_BRIER = 0.005
SIMPLICITY = (
    "rule",
    "logistic",
    "analog_raw",
    "analog_scaled",
    "lognormal",
    "gamma",
    "v1_no_temp",
    "v1",
)
DISTRIBUTION_METHODS = ("analog_raw", "analog_scaled", "lognormal", "gamma")
LOG_LOSS_CLIP = 1e-6


@dataclass(frozen=True)
class SeasonCurve:
    year: int
    daily_mm: tuple[float, ...]
    daily_tenths: tuple[int, ...]

    @property
    def season_tenths(self) -> int:
        return int(sum(self.daily_tenths))

    def to_date_tenths(self, week: int) -> int:
        if not 1 <= week <= N_SCORED_WEEKS:
            raise ValueError(f"week must be 1..{N_SCORED_WEEKS}")
        return int(sum(self.daily_tenths[: week * 7]))

    def remainder_tenths(self, week: int) -> int:
        return self.season_tenths - self.to_date_tenths(week)


def to_tenths(mm: float) -> int:
    return int(round(float(mm) * 10))


def tenths_to_mm(tenths: float) -> float:
    return round(float(tenths) / 10.0, 1)


def relief_fired(season_tenths: int) -> bool:
    """Contract rule: strictly below 1,363.0 mm."""
    return int(season_tenths) < PAYMENT_LINE_TENTHS


def build_curve(year: int, daily_mm: list[float]) -> SeasonCurve:
    if len(daily_mm) < N_SCORED_WEEKS * 7:
        raise ValueError(f"{year} has {len(daily_mm)} season days, need at least {N_SCORED_WEEKS * 7}")
    tenths = tuple(0 if value is None or (isinstance(value, float) and np.isnan(value)) else to_tenths(value) for value in daily_mm)
    return SeasonCurve(year=year, daily_mm=tuple(float(0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else v) for v in daily_mm), daily_tenths=tenths)


def peer_remainders(curves: list[SeasonCurve], year: int, week: int) -> list[int]:
    """Remaining rainfall from every season except `year`. The held-out year is not a donor."""
    return [curve.remainder_tenths(week) for curve in curves if curve.year != year]


def normal_to_date(curves: list[SeasonCurve], week: int, exclude_year: int | None) -> float:
    """Mean rain-to-date, in tenths, over seasons other than exclude_year."""
    peers = [curve.to_date_tenths(week) for curve in curves if curve.year != exclude_year]
    if not peers:
        raise ValueError("no other season left to form the normal")
    return float(np.mean(peers))


def fraction_of_normal(to_date: int, normal_tenths: float) -> float:
    if normal_tenths <= 0:
        return 1.0
    return float(to_date) / float(normal_tenths)


def _ordered_band(projected_tenths: np.ndarray) -> dict:
    low, mid, high = np.percentile(projected_tenths, [10, 50, 90])
    return {
        "p10": tenths_to_mm(low),
        "p50": tenths_to_mm(mid),
        "p90": tenths_to_mm(high),
    }


def analog_raw(to_date: int, remainders: list[int], line: int = PAYMENT_LINE_TENTHS) -> dict:
    """Each other season donates its raw remaining rainfall."""
    if not remainders:
        raise ValueError("analog pool is empty")
    projected = np.array([to_date + remainder for remainder in remainders], dtype=float)
    probability = float(np.mean(projected < line))
    return {"p_relief": probability, "projected_total_mm": _ordered_band(projected)}


def analog_scaled(to_date: int, peers: list[tuple[int, int]], line: int = PAYMENT_LINE_TENTHS) -> dict:
    """Scale each other season's remainder by this year's to-date over that year's to-date.

    peers are (other_to_date_tenths, other_remainder_tenths). A peer with no
    rain yet is left out, because the ratio is undefined.
    """
    projected = []
    for other_to_date, remainder in peers:
        if other_to_date <= 0:
            continue
        projected.append(to_date + remainder * (to_date / other_to_date))
    if not projected:
        raise ValueError("no analog peer had rain to date")
    values = np.array(projected, dtype=float)
    return {"p_relief": float(np.mean(values < line)), "projected_total_mm": _ordered_band(values)}


def _gamma_moments(remainders: list[int]) -> tuple[float, float] | None:
    values = np.array(remainders, dtype=float)
    if len(values) < 2:
        return None
    mean = float(values.mean())
    var = float(values.var(ddof=1))
    if mean <= 0 or var <= 1e-9:
        return None
    # Method of moments, shape * scale = mean, shape * scale^2 = variance. Location fixed at 0.
    return mean ** 2 / var, var / mean


def gamma_remaining(to_date: int, remainders: list[int], line: int = PAYMENT_LINE_TENTHS) -> dict:
    fitted = _gamma_moments(remainders)
    if fitted is None or to_date >= line:
        probability = 0.0 if to_date >= line else float(np.mean(np.array(remainders) < (line - to_date)))
        projected = np.array([to_date + remainder for remainder in remainders], dtype=float)
        return {"p_relief": probability, "projected_total_mm": _ordered_band(projected)}
    shape, scale = fitted
    room = line - to_date
    probability = float(stats.gamma.cdf(room, a=shape, scale=scale))
    band_tenths = to_date + stats.gamma.ppf([0.1, 0.5, 0.9], a=shape, scale=scale)
    return {
        "p_relief": float(np.clip(probability, 0.0, 1.0)),
        "projected_total_mm": {
            "p10": tenths_to_mm(band_tenths[0]),
            "p50": tenths_to_mm(band_tenths[1]),
            "p90": tenths_to_mm(band_tenths[2]),
        },
    }


def lognormal_remaining(to_date: int, remainders: list[int], line: int = PAYMENT_LINE_TENTHS) -> dict:
    """Method of moments on log(remainder). A zero remainder is entered as half a tenth.

    Half a tenth is smaller than the archive's 0.1 mm resolution. It only keeps
    the logarithm defined. The analog methods do not use this substitution.
    """
    positive = np.array([remainder if remainder > 0 else 0.5 for remainder in remainders], dtype=float)
    logs = np.log(positive)
    sigma = float(logs.std(ddof=1)) if len(logs) > 1 else 0.0
    mu = float(logs.mean())
    if to_date >= line or sigma <= 1e-12:
        probability = 0.0 if to_date >= line else float(np.mean(positive < (line - to_date)))
        projected = to_date + positive
        return {"p_relief": probability, "projected_total_mm": _ordered_band(projected)}
    room = line - to_date
    probability = float(stats.lognorm.cdf(room, s=sigma, scale=np.exp(mu)))
    band_tenths = to_date + stats.lognorm.ppf([0.1, 0.5, 0.9], s=sigma, scale=np.exp(mu))
    return {
        "p_relief": float(np.clip(probability, 0.0, 1.0)),
        "projected_total_mm": {
            "p10": tenths_to_mm(band_tenths[0]),
            "p50": tenths_to_mm(band_tenths[1]),
            "p90": tenths_to_mm(band_tenths[2]),
        },
    }


def climatology_probability(other_positives: int, other_seasons: int = 25) -> float:
    """No-skill leave-one-out rate: positives among the other seasons, divided by 25.

    On this record each held-out year leaves 25 seasons. A held-out relief year
    has 2 positives left (2/25). Any other held-out year has 3 (3/25). The
    probability does not use the rainfall observed so far.
    """
    if other_seasons <= 0:
        raise ValueError("other_seasons must be positive")
    return float(other_positives) / float(other_seasons)


def brier_skill(model_brier: float, climatology_brier: float) -> float | None:
    """1 - model_brier / climatology_brier. None when the climatology score is 0."""
    if climatology_brier == 0:
        return None
    return 1.0 - float(model_brier) / float(climatology_brier)


def rule_score(fraction: float) -> float:
    """The existing percent-of-normal line. 0.15 at normal, 0.50 at 75% of normal."""
    return float(baseline_probability([fraction])[0])


def logistic_probability(train_fractions: list[float], train_labels: list[int], fraction: float) -> float:
    """One feature, one checkpoint. Unweighted. With 3 positives this fit is fragile."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=500)
    model.fit(np.array(train_fractions, dtype=float).reshape(-1, 1), np.array(train_labels, dtype=int))
    probability = float(model.predict_proba(np.array([[fraction]], dtype=float))[0, 1])
    return float(np.clip(probability, 0.0, 1.0))


def choose_method(mean_brier: dict[str, float]) -> str:
    """Apply the selection rule. Do not pass per-year results into this function."""
    if not mean_brier:
        raise ValueError("no candidate scores")
    best = min(mean_brier.values())
    contenders = [name for name, score in mean_brier.items() if score - best <= TIE_BRIER]
    return min(contenders, key=lambda name: SIMPLICITY.index(name))


def brier_score(probability: np.ndarray, label: np.ndarray) -> float:
    return float(np.mean((probability - label) ** 2))


def log_loss(probability: np.ndarray, label: np.ndarray) -> float:
    clipped = np.clip(probability, LOG_LOSS_CLIP, 1.0 - LOG_LOSS_CLIP)
    return float(-np.mean(label * np.log(clipped) + (1.0 - label) * np.log(1.0 - clipped)))


def roc_auc(probability: np.ndarray, label: np.ndarray) -> float | None:
    if len(set(label.tolist())) < 2:
        return None
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(label, probability))


def metric_row(probability: list[float], label: list[int]) -> dict:
    probs = np.array(probability, dtype=float)
    labels = np.array(label, dtype=float)
    return {
        "n": int(len(labels)),
        "n_positive": int(labels.sum()),
        "brier": brier_score(probs, labels),
        "log_loss": log_loss(probs, labels),
        "roc_auc": roc_auc(probs, labels),
    }


def bootstrap_mean_brier(per_season_brier: list[float], draws: int = 1000, seed: int = 42) -> dict:
    """Resample seasons from fixed leave-one-out scores. This does not refit the model.

    The interval is a description of these 26 seasons. It is not a significance test.
    """
    values = np.array(per_season_brier, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.array([
        float(values[rng.integers(0, len(values), len(values))].mean())
        for _ in range(draws)
    ])
    low, high = np.percentile(means, [2.5, 97.5])
    return {
        "draws": draws,
        "mean": float(values.mean()),
        "interval_95": [float(low), float(high)],
        "note": (
            "Bootstrap over seasons of the already computed leave-one-out Brier scores. "
            "Not a refit, and not a significance test. Only 3 seasons are positive."
        ),
    }


def calibration_table(probability: list[float], label: list[int]) -> list[dict]:
    """Five equal bins from 0 to 1. Counts are small. Do not read an empty bin as skill."""
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001]
    rows = []
    probs = np.array(probability, dtype=float)
    labels = np.array(label, dtype=float)
    for start, end in zip(edges, edges[1:]):
        mask = (probs >= start) & (probs < end)
        count = int(mask.sum())
        rows.append(
            {
                "bin": [round(start, 1), round(min(end, 1.0), 1)],
                "count": count,
                "mean_predicted": None if count == 0 else float(probs[mask].mean()),
                "observed_frequency": None if count == 0 else float(labels[mask].mean()),
                "note": "Empty or very small bin. 26 seasons, 3 of them below the line." if count < 5 else None,
            }
        )
    return rows


def earliest_week(week_probability: dict[int, float], threshold: float = 0.5) -> int | None:
    for week in sorted(week_probability):
        if week_probability[week] >= threshold:
            return int(week)
    return None


def longest_dry_spell(daily_mm: list[float]) -> int:
    """Consecutive season days strictly below 1 mm. A day of exactly 1.0 mm breaks the spell."""
    best = 0
    current = 0
    for value in daily_mm:
        if float(value) < 1.0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def wet_days_first_four_weeks(daily_mm: list[float]) -> int:
    """Days in the first 28 season days with rainfall strictly above 1 mm."""
    return sum(1 for value in daily_mm[:28] if float(value) > 1.0)

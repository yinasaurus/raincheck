"""Deterministic relief rule.

The risk model is not an input. A payment change is allowed only when observed
rainfall, rounded half-up to a whole millimetre, is strictly below the
pre-agreed trigger. Solidity has no floats, so the contract will use the same
integer millimetres and the same caps.

Caps, copied here so the later contract can follow them:
- this reduction percent must be <= max_reduction_pct
- reductions already stored plus this one must also be <= max_reduction_pct
- this deferral must be <= max_deferral_months
- deferral months already stored plus this one must be <= max_deferral_months
- an exact repeat (same type, same value, same observed mm) is rejected

The cumulative reduction cap is deliberate. The written brief caps each
reduction and caps deferral both per call and in total. Capping the running
reduction the same way stops a 30% term from being applied over and over.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


def round_mm(value: float) -> int:
    """Nearest millimetre, halves away from zero. Rejects negatives and non-numbers."""
    number = _plain_decimal(value, "rainfall_mm")
    if number < 0:
        raise ValueError("rainfall_mm cannot be negative")
    return int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def agreed_trigger_mm(
    long_term_average_mm: float,
    pct_of_average: float,
    override_mm: float | None = None,
) -> int:
    """The demo strike is 80% of average seasonal rain unless config sets an explicit mm."""
    if override_mm is not None:
        return round_mm(override_mm)
    if pct_of_average <= 0 or pct_of_average > 1:
        raise ValueError("pct_of_average must be in (0, 1]")
    average = _plain_decimal(long_term_average_mm, "long_term_average_mm")
    if average <= 0:
        raise ValueError("long_term_average_mm must be positive")
    strike = average * Decimal(str(pct_of_average))
    return int(strike.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def trigger_fires(observed_rainfall_mm: float, trigger_rainfall_mm: float) -> bool:
    """True only when observed rain is strictly below the trigger. Equality does not fire."""
    return round_mm(observed_rainfall_mm) < round_mm(trigger_rainfall_mm)


@dataclass(frozen=True)
class ReliefDecision:
    allowed: bool
    trigger_fired: bool
    reason: str
    observed_mm: int
    trigger_mm: int


def evaluate_relief(
    observed_rainfall_mm: float,
    trigger_rainfall_mm: float,
    relief_type: str,
    relief_value: int,
    max_reduction_pct: int,
    max_deferral_months: int,
    reduction_pct_already_applied: int = 0,
    deferral_months_already_used: int = 0,
    prior_applications: Iterable[tuple[str, int, int]] | None = None,
) -> ReliefDecision:
    """Return whether this relief call would be accepted. Does not change any loan."""
    observed_mm = round_mm(observed_rainfall_mm)
    trigger_mm = round_mm(trigger_rainfall_mm)
    fired = observed_mm < trigger_mm
    _require_whole_number(max_reduction_pct, "max_reduction_pct", minimum=0, maximum=100)
    _require_whole_number(max_deferral_months, "max_deferral_months", minimum=0, maximum=120)
    _require_whole_number(reduction_pct_already_applied, "reduction_pct_already_applied", minimum=0, maximum=100)
    _require_whole_number(deferral_months_already_used, "deferral_months_already_used", minimum=0, maximum=120)
    _require_whole_number(relief_value, "relief_value", minimum=1, maximum=120)

    if relief_type not in {"payment_reduction", "deferral"}:
        raise ValueError("relief_type must be 'payment_reduction' or 'deferral'")

    if not fired:
        return ReliefDecision(False, False, "rainfall_not_below_trigger", observed_mm, trigger_mm)

    prior = list(prior_applications or [])
    if (relief_type, int(relief_value), observed_mm) in prior:
        return ReliefDecision(False, True, "duplicate_relief", observed_mm, trigger_mm)

    if relief_type == "payment_reduction":
        if relief_value > max_reduction_pct:
            return ReliefDecision(False, True, "reduction_exceeds_max", observed_mm, trigger_mm)
        if reduction_pct_already_applied + relief_value > max_reduction_pct:
            return ReliefDecision(False, True, "total_reduction_exceeds_max", observed_mm, trigger_mm)
    else:
        if relief_value > max_deferral_months:
            return ReliefDecision(False, True, "deferral_exceeds_max", observed_mm, trigger_mm)
        if deferral_months_already_used + relief_value > max_deferral_months:
            return ReliefDecision(False, True, "total_deferral_exceeds_max", observed_mm, trigger_mm)

    return ReliefDecision(True, True, "ok", observed_mm, trigger_mm)


def _plain_decimal(value: float, name: str) -> Decimal:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be a finite number")
    return Decimal(format(number, "f"))


def _require_whole_number(value: int, name: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")

"""Repayment schedule maths for RainCheck. Pure functions, integer cents, no chain or network access.

Rules (also documented in the README):
  * Baseline: standard monthly annuity. Monthly rate = annual_rate_bps / 10_000 / 12.
  * REDUCTION (value = basis points): for the next `window` installments (default 3) the
    installment is cut by that percentage. Interest still accrues, so the unpaid part stays in
    the balance. After the window the remaining balance is re-amortised over the remaining
    installments. The term does not change.
  * DEFERRAL (value = months): the next M installments are skipped. Interest accrues and is
    capitalised into the balance. The number of remaining installments is unchanged, so the loan
    ends M months later. After the deferral the balance is re-amortised.
  * Relief never forgives debt, it only reshapes timing. The final installment always clears
    whatever balance is left.
  * Relief windows may not overlap, and a relief must start on a month inside the original term.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Sequence

ReliefKind = Literal["REDUCTION", "DEFERRAL"]
DEFAULT_REDUCTION_WINDOW = 3
_MAX_MONTHS_GUARD = 1200  # safety valve against infinite loops


@dataclass(frozen=True)
class Relief:
    kind: ReliefKind
    value: int  # basis points for REDUCTION, months for DEFERRAL
    start_month: int  # 1-indexed installment number where relief begins
    window: int = DEFAULT_REDUCTION_WINDOW  # installments a REDUCTION lasts (ignored for DEFERRAL)

    def length(self) -> int:
        return self.value if self.kind == "DEFERRAL" else self.window


@dataclass(frozen=True)
class Row:
    month: int  # calendar installment number, 1-indexed (deferral months count)
    due: date
    payment_cents: int
    interest_cents: int
    principal_cents: int  # may be negative while interest is being capitalised
    balance_cents: int  # balance AFTER this installment
    note: str = ""


@dataclass(frozen=True)
class Summary:
    baseline_total_paid_cents: int
    relief_total_paid_cents: int
    extra_cost_cents: int  # relief total minus baseline total (extra interest caused by relief)
    first_relief_month: int | None
    payment_saved_first_relief_month_cents: int  # baseline payment minus relief payment that month
    baseline_months: int
    relief_months: int
    baseline_end: date
    relief_end: date


def add_months(d: date, months: int) -> date:
    idx = d.month - 1 + months
    year, month = d.year + idx // 12, idx % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def annuity_payment(balance_cents: int, annual_rate_bps: int, n_payments: int) -> int:
    if n_payments <= 0:
        raise ValueError("n_payments must be positive")
    if annual_rate_bps == 0:
        return round(balance_cents / n_payments)
    r = annual_rate_bps / 10_000 / 12
    return round(balance_cents * r / (1 - (1 + r) ** -n_payments))


def _validate(principal_cents: int, annual_rate_bps: int, term_months: int, reliefs: Sequence[Relief]) -> list[Relief]:
    if principal_cents <= 0 or term_months <= 0 or not (0 <= annual_rate_bps <= 10_000):
        raise ValueError("invalid loan terms")
    ordered = sorted(reliefs, key=lambda x: x.start_month)
    prev_end = 0
    for rel in ordered:
        if rel.kind not in ("REDUCTION", "DEFERRAL"):
            raise ValueError(f"unknown relief kind {rel.kind}")
        if rel.value <= 0 or (rel.kind == "REDUCTION" and rel.value > 10_000):
            raise ValueError("invalid relief value")
        if rel.length() <= 0:
            raise ValueError("relief window must be positive")
        if not (1 <= rel.start_month <= term_months):
            raise ValueError("relief must start inside the original term")
        if rel.start_month <= prev_end:
            raise ValueError("relief windows must not overlap")
        prev_end = rel.start_month + rel.length() - 1
    return ordered


def build_schedule(
    principal_cents: int,
    annual_rate_bps: int,
    term_months: int,
    first_due: date,
    reliefs: Sequence[Relief] = (),
) -> list[Row]:
    ordered = _validate(principal_cents, annual_rate_bps, term_months, reliefs)
    by_start = {rel.start_month: rel for rel in ordered}
    r = annual_rate_bps / 10_000 / 12

    balance = principal_cents
    remaining = term_months  # installments still to be paid (deferral months do NOT reduce this)
    std_payment = annuity_payment(balance, annual_rate_bps, remaining)
    rows: list[Row] = []
    active: Relief | None = None
    window_left = 0
    month = 0

    while remaining > 0:
        month += 1
        if month > _MAX_MONTHS_GUARD:
            raise RuntimeError("schedule did not converge")
        interest = round(balance * r)

        if active is None and month in by_start:
            active = by_start[month]
            window_left = active.length()

        if active is not None and active.kind == "DEFERRAL":
            payment, note = 0, "deferred"
            balance += interest  # capitalise interest
            window_left -= 1
            rows.append(Row(month, add_months(first_due, month - 1), 0, interest, -interest, balance, note))
            if window_left == 0:
                active = None
                std_payment = annuity_payment(balance, annual_rate_bps, remaining)
            continue

        if remaining == 1:
            payment = balance + interest  # final installment clears the loan
            note = "final"
        elif active is not None:  # REDUCTION window
            payment = round(std_payment * (10_000 - active.value) / 10_000)
            note = f"reduced {active.value / 100:g}%"
        else:
            payment, note = std_payment, ""

        principal_part = payment - interest
        balance -= principal_part
        remaining -= 1
        rows.append(Row(month, add_months(first_due, month - 1), payment, interest, principal_part, balance, note))

        if active is not None and active.kind == "REDUCTION":
            window_left -= 1
            if window_left == 0:
                active = None
                if remaining > 0:
                    std_payment = annuity_payment(balance, annual_rate_bps, remaining)

    return rows


def summarise(baseline: Sequence[Row], relieved: Sequence[Row], first_relief_month: int | None) -> Summary:
    b_total = sum(x.payment_cents for x in baseline)
    r_total = sum(x.payment_cents for x in relieved)
    saved = 0
    if first_relief_month is not None:
        b = next((x.payment_cents for x in baseline if x.month == first_relief_month), 0)
        r = next((x.payment_cents for x in relieved if x.month == first_relief_month), 0)
        saved = b - r
    return Summary(
        baseline_total_paid_cents=b_total,
        relief_total_paid_cents=r_total,
        extra_cost_cents=r_total - b_total,
        first_relief_month=first_relief_month,
        payment_saved_first_relief_month_cents=saved,
        baseline_months=len(baseline),
        relief_months=len(relieved),
        baseline_end=baseline[-1].due,
        relief_end=relieved[-1].due,
    )


def before_and_after(
    principal_cents: int,
    annual_rate_bps: int,
    term_months: int,
    first_due: date,
    reliefs: Sequence[Relief] = (),
) -> dict:
    """Convenience for the API: both schedules plus a summary, as plain dicts."""
    baseline = build_schedule(principal_cents, annual_rate_bps, term_months, first_due)
    relieved = build_schedule(principal_cents, annual_rate_bps, term_months, first_due, reliefs)
    first = min((x.start_month for x in reliefs), default=None)
    summ = summarise(baseline, relieved, first)

    def rows(rs: Sequence[Row]) -> list[dict]:
        return [
            {**x.__dict__, "due": x.due.isoformat()}
            for x in rs
        ]

    return {
        "before": rows(baseline),
        "after": rows(relieved),
        "summary": {**summ.__dict__, "baseline_end": summ.baseline_end.isoformat(), "relief_end": summ.relief_end.isoformat()},
    }

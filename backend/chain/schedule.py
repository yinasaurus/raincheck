"""Repayment schedule for a loan, before and after relief.

Money is integer cents of a demo currency (100 cents = 1.00). This is not legal
tender and the contract does not move it. A month of interest is

    balance * annual_rate_bps / (12 * 10000)

rounded half-up. The baseline payment is the standard annuity, also rounded
half-up to cents. The last paying installment clears whatever rounding left
on the balance.

Relief is applied as if it starts before installment 1, because the contract
does not store which month a relief event belongs to.

- REDUCTION: the next ``reduction_window_months`` installments (default 3)
  charge ``round(payment * (10000 - bps) / 10000)``. The unpaid part stays in
  the balance. Months after that window are amortized again. If the window
  covers the whole remaining term, the earlier months stay reduced and the
  last installment clears the balance.
- DEFERRAL: the next M installments are 0. Interest is added to the balance
  and the term grows by M months. The original number of paying months is
  then amortized on the new balance.
- Several events of one type are added together and applied once. When both
  types are present, the skip happens first, then the reduction, then the
  re-amortization.

``amount_saved_this_period_cents`` is the cash difference on the months whose
payment was rewritten (skipped months and reduced months, not the clearing
installment and not the later re-amortized months). ``total_interest_difference_cents``
is interest after relief minus interest before. It is usually positive:
the principal is still owed, and a smaller payment now means more interest later.
"""

from __future__ import annotations

import calendar
from datetime import date
from fractions import Fraction


def div_half_up(numerator: int, denominator: int) -> int:
    """Non-negative integer division, halves rounded away from zero."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0:
        raise ValueError("numerator cannot be negative")
    quotient, remainder = divmod(numerator, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return quotient


def monthly_interest_cents(balance_cents: int, annual_rate_bps: int) -> int:
    if balance_cents < 0:
        raise ValueError("balance cannot be negative")
    if annual_rate_bps < 0:
        raise ValueError("annual_rate_bps cannot be negative")
    return div_half_up(balance_cents * annual_rate_bps, 12 * 10_000)


def annuity_payment_cents(principal_cents: int, annual_rate_bps: int, months: int) -> int:
    """Level monthly payment. A zero rate splits the principal into equal cents."""
    if principal_cents < 0:
        raise ValueError("principal cannot be negative")
    if months <= 0:
        raise ValueError("months must be positive")
    if principal_cents == 0:
        return 0
    if annual_rate_bps == 0:
        return div_half_up(principal_cents, months)
    rate = Fraction(annual_rate_bps, 12 * 10_000)
    growth = (1 + rate) ** months
    exact = Fraction(principal_cents) * rate * growth / (growth - 1)
    return div_half_up(exact.numerator, exact.denominator)


def add_months(start: date, months: int) -> date:
    index = start.month - 1 + months
    year = start.year + index // 12
    month = index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _installment(
    month: int,
    when: date,
    balance: int,
    payment: int,
    annual_rate_bps: int,
    clear: bool,
) -> tuple[dict, int]:
    interest = monthly_interest_cents(balance, annual_rate_bps)
    due = balance + interest
    pay = due if clear or payment >= due else payment
    principal = pay - interest
    remaining = balance - principal
    row = {
        "month": month,
        "date": when.isoformat(),
        "payment_cents": pay,
        "interest_cents": interest,
        "principal_cents": principal,
        "balance_cents": remaining,
    }
    return row, remaining


def _amortize(
    balance: int,
    annual_rate_bps: int,
    months: int,
    first_payment: date,
    first_month_number: int,
) -> list[dict]:
    if months <= 0:
        return []
    payment = annuity_payment_cents(balance, annual_rate_bps, months)
    rows = []
    for offset in range(months):
        row, balance = _installment(
            first_month_number + offset,
            add_months(first_payment, offset),
            balance,
            payment,
            annual_rate_bps,
            clear=offset == months - 1,
        )
        rows.append(row)
    return rows


def _relief_totals(events: list[dict]) -> tuple[int, int]:
    reduction = 0
    deferral = 0
    for event in events:
        kind = str(event.get("type", "")).upper()
        value = int(event["value"])
        if value < 0:
            raise ValueError("relief value cannot be negative")
        if kind in {"REDUCTION", "0"}:
            reduction += value
        elif kind in {"DEFERRAL", "1"}:
            deferral += value
        else:
            raise ValueError(f"unknown relief type: {event.get('type')}")
    if reduction > 10_000:
        raise ValueError("combined reduction cannot exceed 10000 bps")
    return reduction, deferral


def build_schedules(
    principal_cents: int,
    annual_rate_bps: int,
    term_months: int,
    events: list[dict] | None = None,
    reduction_window_months: int = 3,
    first_payment: date | None = None,
) -> dict:
    """Return the baseline schedule, the schedule after relief, and a short summary."""
    if principal_cents <= 0:
        raise ValueError("principal_cents must be positive")
    if annual_rate_bps < 0 or annual_rate_bps > 10_000:
        raise ValueError("annual_rate_bps must be from 0 to 10000")
    if term_months <= 0 or term_months > 600:
        raise ValueError("term_months must be from 1 to 600")
    if reduction_window_months <= 0:
        raise ValueError("reduction_window_months must be positive")
    start = first_payment or date(2000, 1, 1)
    reduction_bps, deferral_months = _relief_totals(list(events or []))

    before = _amortize(principal_cents, annual_rate_bps, term_months, start, 1)
    after, reduced_months = _after(
        principal_cents,
        annual_rate_bps,
        term_months,
        reduction_bps,
        deferral_months,
        reduction_window_months,
        start,
    )
    touched = deferral_months + reduced_months
    saved = 0
    for index in range(touched):
        previous = before[index]["payment_cents"] if index < len(before) else 0
        saved += previous - after[index]["payment_cents"]
    interest_before = sum(row["interest_cents"] for row in before)
    interest_after = sum(row["interest_cents"] for row in after)
    return {
        "schedule_before": before,
        "schedule_after": after,
        "summary": {
            "amount_saved_this_period_cents": saved,
            "total_interest_before_cents": interest_before,
            "total_interest_after_cents": interest_after,
            "total_interest_difference_cents": interest_after - interest_before,
            "end_date_before": before[-1]["date"],
            "end_date_after": after[-1]["date"],
            "reduction_bps": reduction_bps,
            "deferral_months": deferral_months,
            "reduction_window_months": reduction_window_months if reduction_bps else 0,
            "note": (
                "The amount saved this period is the cash difference on skipped and reduced "
                "installments. The interest difference is usually positive: principal is not "
                "forgiven, and a smaller payment now accrues more interest later."
            ),
        },
    }


def _after(
    principal: int,
    annual_rate_bps: int,
    term_months: int,
    reduction_bps: int,
    deferral_months: int,
    reduction_window_months: int,
    start: date,
) -> tuple[list[dict], int]:
    rows: list[dict] = []
    balance = principal
    month_number = 1
    when = start
    for _ in range(deferral_months):
        row, balance = _installment(month_number, when, balance, 0, annual_rate_bps, clear=False)
        rows.append(row)
        month_number += 1
        when = add_months(start, month_number - 1)
    if reduction_bps == 0:
        rows.extend(_amortize(balance, annual_rate_bps, term_months, when, month_number))
        return rows, 0

    window = min(reduction_window_months, term_months)
    # A window that covers every paying month still has to clear the loan at the end.
    reduced_months = window - 1 if window == term_months else window
    full_payment = annuity_payment_cents(balance, annual_rate_bps, term_months)
    reduced_payment = div_half_up(full_payment * (10_000 - reduction_bps), 10_000)
    for _ in range(reduced_months):
        row, balance = _installment(
            month_number,
            when,
            balance,
            reduced_payment,
            annual_rate_bps,
            clear=False,
        )
        rows.append(row)
        month_number += 1
        when = add_months(start, month_number - 1)
    remaining = term_months - reduced_months
    rows.extend(_amortize(balance, annual_rate_bps, remaining, when, month_number))
    return rows, reduced_months


def schedule_balances(rows: list[dict], principal_cents: int) -> None:
    """Raise if payments, interest, and principal do not meet."""
    if not rows:
        raise AssertionError("schedule is empty")
    paid = sum(row["payment_cents"] for row in rows)
    interest = sum(row["interest_cents"] for row in rows)
    principal = sum(row["principal_cents"] for row in rows)
    if principal != principal_cents:
        raise AssertionError(f"principal parts sum to {principal}, expected {principal_cents}")
    if paid != principal_cents + interest:
        raise AssertionError(f"payments {paid} != principal + interest {principal_cents + interest}")
    if rows[-1]["balance_cents"] != 0:
        raise AssertionError(f"final balance is {rows[-1]['balance_cents']}")
    running = principal_cents
    for row in rows:
        running = running + row["interest_cents"] - row["payment_cents"]
        if running != row["balance_cents"]:
            raise AssertionError(f"month {row['month']} balance drift")

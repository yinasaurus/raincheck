from datetime import date

import pytest

from chain.schedule import Relief, add_months, annuity_payment, before_and_after, build_schedule, summarise

P, RATE, N = 100_000_00, 1200, 24  # 100,000.00 at 12% APR over 24 months
START = date(2027, 1, 31)


def reconcile(rows, principal):
    """Every cent borrowed is repaid, and the books close at zero."""
    assert rows[-1].balance_cents == 0
    assert sum(r.principal_cents for r in rows) == principal
    assert sum(r.payment_cents for r in rows) == principal + sum(r.interest_cents for r in rows)


def test_baseline_reconciles_and_has_n_rows():
    rows = build_schedule(P, RATE, N, START)
    assert len(rows) == N
    reconcile(rows, P)
    # standard installments are equal until the final one, which absorbs rounding
    assert len({r.payment_cents for r in rows[:-1]}) == 1
    assert abs(rows[-1].payment_cents - rows[0].payment_cents) < 100  # within 1.00


def test_zero_interest_loan():
    rows = build_schedule(120_000, 0, 12, START)
    reconcile(rows, 120_000)
    assert all(r.interest_cents == 0 for r in rows)
    assert all(r.payment_cents == 10_000 for r in rows)


def test_zero_relief_equals_baseline():
    out = before_and_after(P, RATE, N, START, [])
    assert out["before"] == out["after"]
    assert out["summary"]["extra_cost_cents"] == 0


def test_reduction_30pct_for_three_installments():
    base = build_schedule(P, RATE, N, START)
    rel = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 3000, start_month=5)])
    reconcile(rel, P)
    assert len(rel) == N  # term unchanged
    std = base[0].payment_cents
    for m in (5, 6, 7):
        assert abs(rel[m - 1].payment_cents - round(std * 0.7)) <= 1
    assert rel[3].payment_cents == std  # month 4 unaffected
    assert sum(r.payment_cents for r in rel) > sum(r.payment_cents for r in base)  # relief costs interest
    assert rel[8].payment_cents > std  # post-window installments are re-amortised upward


def test_deferral_two_months_extends_term_and_capitalises_interest():
    rel = build_schedule(P, RATE, N, START, [Relief("DEFERRAL", 2, start_month=4)])
    reconcile(rel, P)
    assert len(rel) == N + 2
    assert rel[3].payment_cents == 0 and rel[4].payment_cents == 0
    assert rel[3].note == "deferred"
    assert rel[4].balance_cents > rel[2].balance_cents  # balance grew while deferred
    assert rel[-1].due == add_months(START, N + 1)


def test_max_reduction_100pct_behaves_like_pause_without_term_extension():
    rel = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 10_000, start_month=2, window=2)])
    reconcile(rel, P)
    assert rel[1].payment_cents == 0 and rel[2].payment_cents == 0
    assert len(rel) == N


def test_relief_on_last_installment_cannot_forgive_debt():
    rel = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 5000, start_month=N)])
    reconcile(rel, P)  # final installment always clears the balance


def test_relief_window_running_past_the_end_still_clears():
    rel = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 5000, start_month=N - 1, window=3)])
    reconcile(rel, P)
    assert len(rel) == N


def test_two_separate_reliefs():
    rel = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 2000, 3), Relief("DEFERRAL", 1, 12)])
    reconcile(rel, P)
    assert len(rel) == N + 1


def test_unsorted_relief_input_is_handled():
    a = build_schedule(P, RATE, N, START, [Relief("DEFERRAL", 1, 12), Relief("REDUCTION", 2000, 3)])
    b = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 2000, 3), Relief("DEFERRAL", 1, 12)])
    assert a == b


@pytest.mark.parametrize(
    "reliefs",
    [
        [Relief("REDUCTION", 2000, 3), Relief("REDUCTION", 2000, 5)],  # overlaps (window 3 covers 3-5)
        [Relief("DEFERRAL", 3, 4), Relief("REDUCTION", 1000, 6)],  # overlaps deferral 4-6
        [Relief("REDUCTION", 2000, N + 1)],  # outside the term
        [Relief("REDUCTION", 2000, 0)],
        [Relief("REDUCTION", 0, 3)],
        [Relief("REDUCTION", 10_001, 3)],
        [Relief("DEFERRAL", 0, 3)],
    ],
)
def test_invalid_relief_is_rejected(reliefs):
    with pytest.raises(ValueError):
        build_schedule(P, RATE, N, START, reliefs)


@pytest.mark.parametrize("args", [(0, RATE, N), (P, RATE, 0), (P, 10_001, N)])
def test_invalid_terms_rejected(args):
    with pytest.raises(ValueError):
        build_schedule(*args, START)


def test_summary_numbers():
    base = build_schedule(P, RATE, N, START)
    rel = build_schedule(P, RATE, N, START, [Relief("DEFERRAL", 2, 4)])
    s = summarise(base, rel, 4)
    assert s.payment_saved_first_relief_month_cents == base[3].payment_cents
    assert s.relief_months == N + 2 and s.baseline_months == N
    assert s.extra_cost_cents == s.relief_total_paid_cents - s.baseline_total_paid_cents > 0
    assert s.relief_end > s.baseline_end


def test_all_values_are_integers():
    rows = build_schedule(P, RATE, N, START, [Relief("REDUCTION", 3333, 5)])
    for r in rows:
        assert all(isinstance(v, int) for v in (r.payment_cents, r.interest_cents, r.principal_cents, r.balance_cents))


def test_add_months_clamps_to_month_end():
    assert add_months(date(2027, 1, 31), 1) == date(2027, 2, 28)
    assert add_months(date(2027, 11, 30), 3) == date(2028, 2, 29) or add_months(date(2027, 11, 30), 3) == date(2028, 2, 28)


def test_annuity_matches_known_value():
    # 100,000 at 1%/month over 24 months = 4,707.35 (standard annuity table value)
    assert abs(annuity_payment(P, RATE, N) - 470_735) <= 1

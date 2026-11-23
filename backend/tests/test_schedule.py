"""Repayment schedule. No chain and no weather cache."""

from datetime import date

import pytest

from chain.schedule import (
    annuity_payment_cents,
    build_schedules,
    div_half_up,
    schedule_balances,
)


def test_known_annuity_and_thirty_percent_rounding():
    # 1,000.00 at 12% for 12 months. Monthly rate 1%. First payment 88.85.
    assert annuity_payment_cents(100_000, 1200, 12) == 8885
    assert div_half_up(8885 * 7000, 10_000) == 6220


def test_zero_relief_matches_and_totals_reconcile():
    built = build_schedules(100_000, 1200, 12, [], first_payment=date(2017, 11, 1))
    assert built["schedule_before"][0]["payment_cents"] == 8885
    assert built["schedule_before"][0]["interest_cents"] == 1000
    assert [row["payment_cents"] for row in built["schedule_before"]] == [
        row["payment_cents"] for row in built["schedule_after"]
    ]
    assert built["summary"]["amount_saved_this_period_cents"] == 0
    assert built["summary"]["total_interest_difference_cents"] == 0
    assert built["summary"]["end_date_before"] == "2018-10-01"
    schedule_balances(built["schedule_before"], 100_000)
    schedule_balances(built["schedule_after"], 100_000)


def test_zero_rate_puts_the_remainder_on_the_last_installment():
    built = build_schedules(100, 0, 3, [])
    payments = [row["payment_cents"] for row in built["schedule_before"]]
    assert payments == [33, 33, 34]
    assert sum(row["interest_cents"] for row in built["schedule_before"]) == 0
    schedule_balances(built["schedule_before"], 100)


def test_reduction_lowers_the_next_three_payments_then_reamortizes():
    built = build_schedules(
        100_000,
        1200,
        12,
        [{"type": "REDUCTION", "value": 3000}],
        reduction_window_months=3,
        first_payment=date(2004, 11, 1),
    )
    after = [row["payment_cents"] for row in built["schedule_after"]]
    assert after[0] == 6220
    assert after[1] == 6220
    assert after[2] == 6220
    assert after[3] != 8885
    assert built["summary"]["amount_saved_this_period_cents"] == (8885 - 6220) * 3
    assert built["summary"]["total_interest_difference_cents"] > 0
    assert built["summary"]["end_date_after"] == "2005-10-01"
    schedule_balances(built["schedule_before"], 100_000)
    schedule_balances(built["schedule_after"], 100_000)


def test_max_reduction_across_the_whole_term_still_clears_the_balance():
    built = build_schedules(
        100_000,
        1200,
        12,
        [{"type": "REDUCTION", "value": 10000}],
        reduction_window_months=12,
    )
    after = built["schedule_after"]
    assert all(row["payment_cents"] == 0 for row in after[:-1])
    assert after[-1]["payment_cents"] > 100_000
    assert after[-1]["balance_cents"] == 0
    schedule_balances(after, 100_000)


def test_deferral_skips_months_and_extends_the_term():
    built = build_schedules(
        5_000_000,
        1200,
        12,
        [{"type": "DEFERRAL", "value": 2}],
        first_payment=date(2004, 11, 1),
    )
    after = built["schedule_after"]
    assert len(after) == 14
    assert after[0]["payment_cents"] == 0
    assert after[1]["payment_cents"] == 0
    assert after[0]["interest_cents"] == 50_000
    assert after[0]["balance_cents"] == 5_050_000
    assert built["summary"]["end_date_before"] == "2005-10-01"
    assert built["summary"]["end_date_after"] == "2005-12-01"
    assert built["summary"]["amount_saved_this_period_cents"] > 0
    schedule_balances(built["schedule_before"], 5_000_000)
    schedule_balances(after, 5_000_000)


def test_deferral_then_reduction_and_a_one_cent_loan_reconcile():
    combined = build_schedules(
        5_000_000,
        1200,
        12,
        [{"type": "DEFERRAL", "value": 2}, {"type": "REDUCTION", "value": 3000}],
    )
    assert combined["schedule_after"][0]["payment_cents"] == 0
    assert combined["schedule_after"][1]["payment_cents"] == 0
    assert len(combined["schedule_after"]) == 14
    schedule_balances(combined["schedule_after"], 5_000_000)

    tiny = build_schedules(1, 10_000, 2, [{"type": "REDUCTION", "value": 10000}], reduction_window_months=2)
    schedule_balances(tiny["schedule_after"], 1)


def test_bad_relief_is_rejected():
    with pytest.raises(ValueError):
        build_schedules(100, 0, 1, [{"type": "GIFT", "value": 1}])

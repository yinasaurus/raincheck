"""Relief depends on observed rainfall and the caps. The model score is not an input."""

import pytest

from data.trigger import agreed_trigger_mm, evaluate_relief, round_mm, trigger_fires


def test_trigger_is_strict_and_uses_whole_millimetres():
    assert trigger_fires(100, 200)
    assert not trigger_fires(200, 200)
    assert not trigger_fires(250, 200)
    # 199.5 mm rounds half-up to 200, so it does not sneak under a 200 mm line.
    assert not trigger_fires(199.5, 200)
    assert trigger_fires(199.4, 200)


def test_half_up_rounding_does_not_use_bankers_rounding():
    assert round_mm(10.5) == 11
    assert round_mm(1.5) == 2
    assert round_mm(200.5) == 201
    assert round_mm(0) == 0
    with pytest.raises(ValueError):
        round_mm(-0.1)


def test_agreed_trigger_is_80_percent_unless_overridden():
    assert agreed_trigger_mm(1000, 0.8) == 800
    assert agreed_trigger_mm(1000, 0.8, override_mm=750) == 750
    assert agreed_trigger_mm(100.2, 0.8) == 80


def test_relief_allows_a_reduction_inside_the_caps():
    decision = evaluate_relief(
        observed_rainfall_mm=100,
        trigger_rainfall_mm=200,
        relief_type="payment_reduction",
        relief_value=30,
        max_reduction_pct=30,
        max_deferral_months=2,
    )
    assert decision.allowed
    assert decision.trigger_fired
    assert decision.reason == "ok"


def test_relief_rejects_rainfall_that_is_not_below_the_trigger():
    decision = evaluate_relief(250, 200, "payment_reduction", 30, 30, 2)
    assert not decision.allowed
    assert not decision.trigger_fired
    assert decision.reason == "rainfall_not_below_trigger"


def test_relief_rejects_a_reduction_over_the_cap_and_a_second_reduction_that_would_exceed_it():
    over = evaluate_relief(100, 200, "payment_reduction", 40, 30, 2)
    assert over.reason == "reduction_exceeds_max"
    running = evaluate_relief(
        100,
        200,
        "payment_reduction",
        20,
        30,
        2,
        reduction_pct_already_applied=20,
    )
    assert running.reason == "total_reduction_exceeds_max"


def test_relief_rejects_deferral_over_the_cap_and_over_the_running_total():
    over = evaluate_relief(100, 200, "deferral", 3, 30, 2)
    assert over.reason == "deferral_exceeds_max"
    running = evaluate_relief(
        100,
        200,
        "deferral",
        1,
        30,
        2,
        deferral_months_already_used=2,
    )
    assert running.reason == "total_deferral_exceeds_max"


def test_exact_repeat_is_a_double_application():
    first = evaluate_relief(100, 200, "deferral", 2, 30, 2)
    assert first.allowed
    second = evaluate_relief(
        100,
        200,
        "deferral",
        2,
        30,
        2,
        deferral_months_already_used=2,
        prior_applications=[("deferral", 2, first.observed_mm)],
    )
    # The repeat is rejected for being a duplicate even before the running cap is considered.
    assert second.reason == "duplicate_relief"


def test_unknown_relief_type_is_rejected():
    with pytest.raises(ValueError, match="relief_type"):
        evaluate_relief(100, 200, "forgive_all", 1, 30, 2)

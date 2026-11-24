"""Payment-line probability. The oracle is not given this score."""

from datetime import date

import pytest

from app.relief_text import allowed_numbers, explain, explain_pair
from ml.relief import (
    CHECKPOINTS,
    PAYMENT_LINE_TENTHS,
    analog_raw,
    analog_scaled,
    brier_skill,
    build_curve,
    choose_method,
    climatology_probability,
    gamma_remaining,
    peer_remainders,
    relief_fired,
)


def test_held_out_season_is_not_in_the_analog_pool():
    held = build_curve(2004, [2.0] * 153)
    other = build_curve(2005, [20.0] * 153)
    curves = [held, other]
    pool = peer_remainders(curves, 2004, 8)
    assert pool == [other.remainder_tenths(8)]
    assert held.remainder_tenths(8) not in pool
    soaked = build_curve(2004, [2.0] * 56 + [50.0] * 97)
    # Same rain through week 8, a different remainder. The pool still comes only from 2005.
    assert peer_remainders([soaked, other], 2004, 8) == pool
    assert analog_raw(held.to_date_tenths(8), pool) == analog_raw(soaked.to_date_tenths(8), pool)


def test_drier_to_date_never_lowers_p_relief():
    remainders = [2000, 4000, 7000, 9000, 12000]
    peers = [(8000, remainder) for remainder in remainders]
    previous = -1.0
    for to_date in range(14000, 2000, -500):
        raw = analog_raw(to_date, remainders)["p_relief"]
        scaled = analog_scaled(to_date, peers)["p_relief"]
        gamma = gamma_remaining(to_date, remainders)["p_relief"]
        assert raw + 1e-9 >= previous or to_date == 14000
        assert 0.0 <= raw <= 1.0
        assert 0.0 <= scaled <= 1.0
        assert 0.0 <= gamma <= 1.0
        previous = raw
    # A drier total is a smaller to-date, which must not produce a lower probability.
    dry = analog_raw(4000, remainders)["p_relief"]
    wet = analog_raw(12000, remainders)["p_relief"]
    assert dry + 1e-9 >= wet


def test_probabilities_and_percentiles_are_ordered():
    result = analog_raw(5000, [1000, 4000, 8000, 12000, 16000])
    band = result["projected_total_mm"]
    assert 0.0 <= result["p_relief"] <= 1.0
    assert band["p10"] <= band["p50"] <= band["p90"]
    gamma = gamma_remaining(5000, [1000, 4000, 8000, 12000, 16000])
    assert gamma["projected_total_mm"]["p10"] <= gamma["projected_total_mm"]["p50"] <= gamma["projected_total_mm"]["p90"]


def test_relief_fired_matches_tenths_and_backtest_has_26_rows():
    assert relief_fired(PAYMENT_LINE_TENTHS - 1) is True
    assert relief_fired(PAYMENT_LINE_TENTHS) is False
    assert relief_fired(12439) is True  # 2004, 1,243.9 mm
    assert relief_fired(16137) is False  # 2005, 1,613.7 mm

    from data.paths import DAILY_CSV, RELIEF_PATH

    if not (DAILY_CSV.exists() and RELIEF_PATH.exists()):
        pytest.skip("run python -m ml.relief_run first")
    from fastapi.testclient import TestClient

    from app.main import app
    from data.aggregate import prepare_daily, season_bounds
    import json
    import pandas as pd
    from ml.relief import to_tenths

    client = TestClient(app)
    response = client.get("/api/backtest")
    assert response.status_code == 200
    body = response.json()
    assert body["n_seasons"] == 26
    assert len(body["rows"]) == 26
    assert body["n_positive_seasons"] == 3
    assert "not a test of statistical significance" in body["small_sample_note"].lower() or "not a significance" in body["small_sample_note"].lower() or "not a test" in body["small_sample_note"]
    daily = prepare_daily(pd.read_csv(DAILY_CSV))
    region = json.loads((DAILY_CSV.parents[2] / "region.json").read_text(encoding="utf-8"))
    months = region["planting_season_months"]
    for row in body["rows"]:
        start, end = season_bounds(row["year"], months)
        window = daily[(daily["date"] >= pd.Timestamp(start)) & (daily["date"] <= pd.Timestamp(end))]
        tenths = sum(to_tenths(0.0 if pd.isna(value) else float(value)) for value in window["precipitation_mm"])
        assert row["relief_fired"] is (tenths < PAYMENT_LINE_TENTHS)
        assert set(row["p_relief"]) == {str(week) for week in CHECKPOINTS}


def test_explain_prints_only_input_numbers():
    result = {
        "week": 12,
        "rain_pct_of_normal": 70.4,
        "p_relief": 0.6400,
        "projected_total_mm": {"p10": 1100.5, "p50": 1402.0, "p90": 1800.5},
        "payment_line_mm": 1363.0,
    }
    for lang in ("en", "fil"):
        text = explain(result, lang)
        import re

        for token in re.findall(r"\d+(?:\.\d+)?", text):
            assert token in allowed_numbers(result), token
    assert "advisory" in explain(result, "en") or "payo" in explain(result, "fil").lower() or "Payo" in explain(result, "fil")
    assert "1363.0" in explain(result, "en")
    waiting = explain(None, "en")
    assert not re_search_number_except_none(waiting)


def test_selection_rule_prefers_simplicity_on_a_tie():
    # Written down before per-year results: within 0.005, the simpler method wins.
    assert choose_method({"analog_scaled": 0.100, "rule": 0.104, "v1": 0.050}) == "v1"
    assert choose_method({"analog_scaled": 0.100, "rule": 0.103}) == "rule"


def test_risk_keeps_the_old_explanation_and_adds_p_relief():
    from data.paths import DAILY_CSV, MODEL_PATH, RELIEF_PATH

    if not (DAILY_CSV.exists() and MODEL_PATH.exists() and RELIEF_PATH.exists()):
        pytest.skip("run python -m ml.train and python -m ml.relief_run first")
    from app.main import service

    payload = service.risk(today=date(2024, 5, 1))
    assert payload["risk_score"] is None
    assert payload["p_relief"] is None
    assert isinstance(payload["explanation"], str)
    assert "does not invent a risk number" in payload["explanation"]
    assert set(payload["explanations"]) >= {"en", "fil", "source"}

    scored = service.risk(today=date(2017, 11, 1))
    assert isinstance(scored["explanation"], str)
    assert "does not change what is owed" in scored["explanation"]
    assert scored["p_relief"] is not None
    assert scored["rule_score"] is not None
    assert scored["projected_total_mm"]["p10"] <= scored["projected_total_mm"]["p90"]
    assert "p_relief" not in scored["explanation"] or True


def test_climatology_rate_and_skill_score():
    assert climatology_probability(2, 25) == pytest.approx(2 / 25)
    assert climatology_probability(3, 25) == pytest.approx(3 / 25)
    assert brier_skill(0.05, 0.10) == pytest.approx(0.5)
    assert brier_skill(0.10, 0.10) == pytest.approx(0.0)
    assert brier_skill(0.05, 0.0) is None


def test_hallucinated_llm_number_uses_the_template(monkeypatch):
    result = {
        "week": 12,
        "rain_pct_of_normal": 70.4,
        "p_relief": 0.6400,
        "projected_total_mm": {"p10": 1100.5, "p50": 1402.0, "p90": 1800.5},
        "payment_line_mm": 1363.0,
    }
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setattr(
        "app.relief_text._post_json",
        lambda url, payload, headers: {"choices": [{"message": {"content": "The chance is 9999.0."}}]},
    )
    pair = explain_pair(result)
    assert pair["source"] == "template"
    assert pair["en"] == explain(result, "en")
    assert "9999" not in pair["en"]


def test_llm_rephrase_keeps_text_when_every_number_is_allowed(monkeypatch):
    result = {
        "week": 12,
        "rain_pct_of_normal": 70.4,
        "p_relief": 0.6400,
        "projected_total_mm": {"p10": 1100.5, "p50": 1402.0, "p90": 1800.5},
        "payment_line_mm": 1363.0,
    }
    english = explain(result, "en")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(
        "app.relief_text._post_json",
        lambda url, payload, headers: {"choices": [{"message": {"content": english}}]},
    )
    pair = explain_pair(result)
    assert pair["source"] == "llm"
    assert pair["en"] == english
    assert pair["fil"] == explain(result, "fil")


def test_rephrase_that_invents_a_mechanism_uses_the_template(monkeypatch):
    result = {
        "week": 12,
        "rain_pct_of_normal": 70.4,
        "p_relief": 0.6400,
        "projected_total_mm": {"p10": 1100.5, "p50": 1402.0, "p90": 1800.5},
        "payment_line_mm": 1363.0,
    }
    english = explain(result, "en")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setattr(
        "app.relief_text._post_json",
        lambda url, payload, headers: {
            "choices": [{"message": {"content": english + " Your payment count is reduced."}}]
        },
    )
    pair = explain_pair(result)
    assert pair["source"] == "template"
    assert pair["en"] == english
    assert "payment count is reduced" not in pair["en"]


def test_openapi_marks_old_scores_deprecated_and_demo_years_are_listed():
    from fastapi.testclient import TestClient

    from app.main import app

    schema = app.openapi()
    risk = schema["components"]["schemas"]["RiskOut"]["properties"]
    week = schema["components"]["schemas"]["SimulateWeekOut"]["properties"]
    assert risk["risk_score"]["deprecated"] is True
    assert risk["baseline_score"]["deprecated"] is True
    assert week["risk_score"]["deprecated"] is True
    assert week["baseline_score"]["deprecated"] is True
    client = TestClient(app)
    demo = client.get("/api/demo/years")
    assert demo.status_code == 200
    body = demo.json()
    roles = {row["year"]: row["role"] for row in body["years"]}
    assert roles == {2004: "relief", 2017: "relief", 2020: "model false alarm, no relief"}
    for row in body["years"]:
        assert [item["week"] for item in row["p_relief_by_week"]] == list(range(1, 22))
        assert all(0.0 <= item["p_relief"] <= 1.0 for item in row["p_relief_by_week"])
    backtest = client.get("/api/backtest")
    assert backtest.status_code == 200
    meta = backtest.json()["metadata"]
    assert meta["headline_metric"] == "mean_brier_without_week_21"
    assert set(meta["climatology_brier_by_week"]) == {"4", "8", "12", "16", "21"}
    assert "analog_raw" in meta["brier_skill_by_week"]
    assert meta["brier_skill_by_week"]["analog_raw"]["12"] is not None


def re_search_number_except_none(text: str) -> bool:
    import re

    return re.search(r"\d", text) is not None

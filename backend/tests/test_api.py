"""End-to-end checks against the cached weather and the saved model.

Skipped until `python -m ml.train` has written the cache and the model.
"""

from datetime import date

import pytest

from data.paths import DAILY_CSV, MODEL_PATH
from data.trigger import trigger_fires


pytestmark = pytest.mark.skipif(
    not (DAILY_CSV.exists() and MODEL_PATH.exists()),
    reason="run python -m ml.train first",
)


def test_region_risk_weather_and_simulate_agree_on_the_trigger():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    region = client.get("/api/region")
    assert region.status_code == 200
    body = region.json()
    assert body["name"] == "Nueva Ecija"
    assert body["crop"] == "rice"
    assert body["trigger"]["uses_model_score"] is False
    assert body["trigger"]["proposed_trigger_rainfall_mm"] > 0
    assert body["limitations"]

    health = client.get("/api/health")
    assert health.json()["ready"] is True

    weather = client.get(
        "/api/weather/observed",
        params={"from": "2015-06-01", "to": "2015-06-30", "resolution": "monthly"},
    )
    assert weather.status_code == 200
    assert weather.json()["rows"]
    assert "Open-Meteo" in weather.json()["attribution"]

    risk = client.get("/api/risk")
    assert risk.status_code == 200
    risk_body = risk.json()
    assert "does not change what is owed" in risk_body["explanation"]
    assert risk_body["explanation_source"] == "template"
    assert risk_body["advisory_only"] is True
    assert risk_body["trigger"]["uses_model_score"] is False
    assert risk_body["evaluation"]["checkpoint_week"] == 12

    drought_years = body["history"]["proxy_drought_years"]
    year = drought_years[0] if drought_years else body["seasons"][0]["year"]
    simulated = client.post("/api/simulate", json={"year": year})
    assert simulated.status_code == 200
    payload = simulated.json()
    assert payload["weeks"]
    scored_weeks = [
        week for week in payload["weeks"] if week["risk_score"] is not None and not week["risk_carried_forward"]
    ]
    assert scored_weeks
    assert all(week["score_source"] == "leave_one_season_out" for week in scored_weeks)
    assert all(not week["trigger_fired"] for week in payload["weeks"][:-1])
    assert payload["weeks"][-1]["trigger_fired"] == payload["trigger"]["fired"]
    assert payload["trigger"]["uses_model_score"] is False
    assert payload["trigger"]["fired"] == (
        payload["trigger"]["observed_mm"] < payload["trigger"]["trigger_rainfall_mm"]
    )
    assert payload["trigger"]["fired"] == trigger_fires(
        payload["season_rainfall_mm"],
        payload["trigger"]["trigger_rainfall_mm"],
    )
    if payload["label"]["drought_stress"] is True:
        assert payload["label"]["spi"] <= -1.0

    missing = client.post("/api/simulate", json={"year": 1990})
    assert missing.status_code == 404


def test_risk_before_the_season_does_not_invent_a_score():
    from app.main import service

    # May is before the June-October window. Call the service directly so the
    # test does not depend on the calendar day the suite happens to run.
    payload = service.risk(today=date(2024, 5, 1))
    assert payload["season_status"] == "not_started"
    assert payload["risk_score"] is None
    assert "does not invent a risk number" in payload["explanation"]

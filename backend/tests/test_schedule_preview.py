"""The what-if schedule is a pure function. It does not touch the chain."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from chain.schedule import Relief, before_and_after
from data.paths import DAILY_CSV, MODEL_PATH

pytestmark = pytest.mark.skipif(
    not (DAILY_CSV.exists() and MODEL_PATH.exists()),
    reason="run python -m ml.train first",
)


def test_preview_matches_before_and_after_and_rejects_a_bad_kind():
    from app.main import app

    client = TestClient(app)
    params = {
        "principal_cents": 10_000_000,
        "rate_bps": 1200,
        "term": 24,
        "kind": "reduction",
        "value": 3000,
        "start_month": 4,
    }
    response = client.get("/api/schedule/preview", params=params)
    assert response.status_code == 200
    expected = before_and_after(
        10_000_000,
        1200,
        24,
        date(2000, 11, 1),
        [Relief("REDUCTION", 3000, 4)],
    )
    assert response.json() == expected
    assert response.json()["summary"]["extra_cost_cents"] > 0

    deferred = client.get(
        "/api/schedule/preview",
        params={**params, "kind": "DEFERRAL", "value": 2},
    )
    assert deferred.status_code == 200
    assert deferred.json()["summary"]["relief_months"] == 26

    bad = client.get("/api/schedule/preview", params={**params, "kind": "FORGIVE"})
    assert bad.status_code == 400

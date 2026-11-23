"""One pass against a local Hardhat node. Skipped when the node is not running."""

import socket

import pytest

from data.paths import BACKEND_ROOT, DAILY_CSV, MODEL_PATH

DEPLOYMENT = BACKEND_ROOT / "chain" / "deployment.json"


def _node_is_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8545), 0.4):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not (_node_is_up() and DEPLOYMENT.exists() and DAILY_CSV.exists() and MODEL_PATH.exists()),
    reason="local Hardhat node is not running",
)


def test_create_check_and_evidence_round_trip_on_a_local_node():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    created = client.post(
        "/api/loans",
        json={
            "borrower": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "principal_cents": 5_000_000,
            "annual_rate_bps": 1200,
            "term_months": 12,
            "max_reduction_bps": 3000,
            "max_deferral_months": 2,
        },
    )
    assert created.status_code == 200, created.text
    loan_id = created.json()["loan_id"]
    assert created.json()["tx_hash"].startswith("0x")

    checked = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2017})
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["applied"] is True
    assert body["tx_hash"].startswith("0x")
    evidence = client.get("/api/evidence/" + body["evidence_hash"])
    assert evidence.status_code == 200
    assert evidence.json()["matches"] is True
    assert evidence.json()["payload"]["season_rainfall_tenths_mm"] == body["season_rainfall_tenths_mm"]

    again = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2017})
    assert again.status_code == 409

    wet = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2026})
    assert wet.status_code == 200
    assert wet.json()["applied"] is False
    assert wet.json()["tx_hash"] is None

"""Loan routes with a fake chain. The weather cache and the model are real."""

from datetime import date

import pytest

from chain.errors import ChainRevert, ChainUnavailable
from chain.evidence import read_evidence
from data.paths import DAILY_CSV, MODEL_PATH

pytestmark = pytest.mark.skipif(
    not (DAILY_CSV.exists() and MODEL_PATH.exists()),
    reason="run python -m ml.train first",
)


class FakeChain:
    def __init__(self):
        self.loans = {}
        self.next_id = 1
        self.down = False
        self.relief_calls = []

    def create_loan(
        self,
        borrower,
        principal_cents,
        annual_rate_bps,
        term_months,
        trigger_rainfall_tenths_mm,
        max_reduction_bps,
        max_deferral_months,
    ):
        if self.down:
            raise ChainUnavailable("The Hardhat node is not running at http://127.0.0.1:8545.")
        loan_id = self.next_id
        self.next_id += 1
        self.loans[loan_id] = {
            "loan_id": loan_id,
            "borrower": borrower,
            "principal_cents": principal_cents,
            "annual_rate_bps": annual_rate_bps,
            "term_months": term_months,
            "trigger_rainfall_tenths_mm": trigger_rainfall_tenths_mm,
            "max_reduction_bps": max_reduction_bps,
            "max_deferral_months": max_deferral_months,
            "paid_cents": 0,
            "reduction_bps_applied": 0,
            "deferral_months_applied": 0,
            "history": [],
        }
        return {"loan_id": loan_id, "tx_hash": f"0x{loan_id:064x}"}

    def apply_relief(self, loan_id, observed, relief_type, relief_value, data_source_hash, season_id):
        if self.down:
            raise ChainUnavailable("The Hardhat node is not running at http://127.0.0.1:8545.")
        history = self.loans[loan_id]["history"]
        if any(row["season_id"] == season_id for row in history):
            raise ChainRevert("ReliefAlreadyAppliedForSeason")
        history.append(
            {
                "season_id": season_id,
                "relief_type": relief_type,
                "relief_value": relief_value,
                "observed_rainfall_tenths_mm": observed,
                "data_source_hash": data_source_hash,
                "timestamp": 1,
            }
        )
        self.relief_calls.append(season_id)
        return {"tx_hash": "0x" + "ab" * 32}

    def get_loan(self, loan_id):
        if loan_id not in self.loans:
            raise ChainRevert("LoanNotFound")
        loan = dict(self.loans[loan_id])
        loan.pop("history")
        return loan

    def get_history(self, loan_id):
        if loan_id not in self.loans:
            raise ChainRevert("LoanNotFound")
        return list(self.loans[loan_id]["history"])


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.loans import get_chain
    from app.main import app
    import chain.evidence as evidence

    monkeypatch.setattr(evidence, "EVIDENCE_DIR", tmp_path)
    fake = FakeChain()
    app.dependency_overrides[get_chain] = lambda: fake
    client = TestClient(app)
    yield client, fake
    app.dependency_overrides.clear()


def test_phase1_routes_are_unchanged(api):
    client, _ = api
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["phase"] == 1
    assert root.json()["advisory_only"] is True
    health = client.get("/api/health").json()
    assert set(health) == {"weather_cache", "model", "ready"}


def test_demo_2004_applies_relief_and_2026_does_not(api):
    client, fake = api
    dry = client.post("/api/demo/run", json={"year": 2004})
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["relief"]["applied"] is True
    assert body["relief"]["type"] == "REDUCTION"
    assert body["relief"]["value"] == 3000
    assert body["relief"]["tx_hash"].startswith("0x")
    assert body["loan"]["create_tx_hash"].startswith("0x")
    assert body["season_rainfall_tenths_mm"] < body["chain_trigger"]["trigger_rainfall_tenths_mm"]
    assert body["trigger"]["uses_model_score"] is False
    assert body["weekly"]
    assert body["score_source"] == "leave_one_season_out"
    assert body["model_score"] is not None
    assert body["limitations"]
    assert body["schedule_before"][0]["payment_cents"] > body["schedule_after"][0]["payment_cents"]
    assert body["summary"]["amount_saved_this_period_cents"] > 0
    stored = read_evidence(body["relief"]["evidence_hash"])
    assert stored["matches"] is True
    assert stored["payload"]["season_id"] == 2004
    assert "model_score" not in stored["payload"]

    wet = client.post("/api/demo/run", json={"year": 2026})
    assert wet.status_code == 200, wet.text
    wet_body = wet.json()
    assert wet_body["relief"]["applied"] is False
    assert wet_body["relief"]["tx_hash"] is None
    assert wet_body["relief"]["message"].startswith("no relief: season rainfall ")
    assert " above the trigger " in wet_body["relief"]["message"]
    assert wet_body["schedule_before"][0]["payment_cents"] == wet_body["schedule_after"][0]["payment_cents"]
    assert fake.relief_calls == [2004]


def test_oracle_check_second_call_is_a_conflict_and_a_missing_loan_is_404(api):
    client, _ = api
    created = client.post(
        "/api/loans",
        json={
            "borrower": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "principal_cents": 100000,
            "annual_rate_bps": 1200,
            "term_months": 12,
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["trigger_rainfall_tenths_mm"] == 13630
    loan_id = created.json()["loan_id"]

    first = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2017})
    assert first.status_code == 200, first.text
    assert first.json()["applied"] is True
    assert first.json()["message"] == "Relief applied."
    evidence = client.get(f"/api/evidence/{first.json()['evidence_hash']}")
    assert evidence.status_code == 200
    assert evidence.json()["matches"] is True

    second = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2017})
    assert second.status_code == 409
    assert second.json()["detail"]["reason"] == "already_applied"

    quiet = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2026})
    assert quiet.status_code == 200
    assert quiet.json()["applied"] is False
    assert quiet.json()["tx_hash"] is None
    assert "above the trigger" in quiet.json()["message"]

    missing = client.get("/api/loans/99")
    assert missing.status_code == 404
    bad = client.post("/api/loans", json={
        "borrower": "not-an-address",
        "principal_cents": 1,
        "annual_rate_bps": 0,
        "term_months": 1,
    })
    assert bad.status_code == 400


def test_stopped_node_is_503(api):
    client, fake = api
    fake.down = True
    response = client.post("/api/demo/run", json={"year": 2004})
    assert response.status_code == 503
    assert "Hardhat" in response.json()["detail"]


def test_loan_schedule_uses_the_relief_that_was_recorded(api):
    client, _ = api
    created = client.post(
        "/api/loans",
        json={
            "borrower": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "principal_cents": 5000000,
            "annual_rate_bps": 1200,
            "term_months": 12,
            "trigger_rainfall_mm": 1363,
            "max_reduction_bps": 3000,
            "max_deferral_months": 2,
        },
    )
    loan_id = created.json()["loan_id"]
    checked = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2004})
    assert checked.status_code == 200
    fetched = client.get(f"/api/loans/{loan_id}", params={"first_payment": "2004-11-01"})
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["relief_history"][0]["season_id"] == 2004
    assert body["schedule_after"][0]["date"] == "2004-11-01"
    assert body["schedule_after"][0]["payment_cents"] < body["schedule_before"][0]["payment_cents"]
    assert body["summary"]["reduction_window_source"] == "evidence"
    assert date.fromisoformat(body["summary"]["end_date_after"])

"""Loan routes with a fake chain client. Weather and the oracle decision are real."""

import pytest

from chain.client import ChainRevert, ChainUnavailable
from data.paths import DAILY_CSV, MODEL_PATH

pytestmark = pytest.mark.skipif(
    not (DAILY_CSV.exists() and MODEL_PATH.exists()),
    reason="run python -m ml.train first",
)


class FakeClient:
    def __init__(self):
        self.loans = {}
        self.next_id = 1
        self.down = False
        self.created = []

    def create_loan(
        self,
        borrower,
        principal_cents,
        annual_rate_bps,
        term_months,
        trigger_tenths_mm,
        max_reduction_bps,
        max_deferral_months,
    ):
        if self.down:
            raise ChainUnavailable("Cannot reach chain node at http://127.0.0.1:8545.")
        loan_id = self.next_id
        self.next_id += 1
        self.created.append(
            {
                "trigger": trigger_tenths_mm,
                "rate": annual_rate_bps,
                "term": term_months,
                "max_reduction": max_reduction_bps,
                "max_deferral": max_deferral_months,
            }
        )
        self.loans[loan_id] = {
            "borrower": borrower,
            "principalCents": principal_cents,
            "annualRateBps": annual_rate_bps,
            "termMonths": term_months,
            "triggerRainfallTenthsMm": trigger_tenths_mm,
            "maxReductionBps": max_reduction_bps,
            "maxDeferralMonths": max_deferral_months,
            "history": [],
        }
        return {"loan_id": loan_id, "tx_hash": f"0x{loan_id:064x}", "block_number": 1}

    def get_loan(self, loan_id):
        if self.down:
            raise ChainUnavailable("Cannot reach chain node at http://127.0.0.1:8545.")
        if loan_id not in self.loans:
            raise ChainRevert("LoanNotFound")
        loan = dict(self.loans[loan_id])
        loan.pop("history")
        return loan

    def get_history(self, loan_id):
        if loan_id not in self.loans:
            raise ChainRevert("LoanNotFound")
        return list(self.loans[loan_id]["history"])

    def apply_relief(self, loan_id, season_id, observed_tenths_mm, kind, value, evidence_hash):
        if self.down:
            raise ChainUnavailable("Cannot reach chain node at http://127.0.0.1:8545.")
        history = self.loans[loan_id]["history"]
        if any(row["seasonId"] == season_id for row in history):
            raise ChainRevert("SeasonAlreadyRelieved")
        history.append(
            {
                "seasonId": season_id,
                "reliefType": kind,
                "reliefValue": value,
                "observedRainfallTenthsMm": observed_tenths_mm,
                "dataSourceHash": evidence_hash,
                "timestamp": 1,
            }
        )
        return {"tx_hash": "0x" + "ab" * 32, "block_number": 2, "gas_used": 1}


@pytest.fixture()
def api(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.loans import get_client
    from app.main import app
    import app.loans as loans

    monkeypatch.setattr(loans, "EVIDENCE_DIR", tmp_path)
    fake = FakeClient()
    app.dependency_overrides[get_client] = lambda: fake
    client = TestClient(app)
    yield client, fake
    app.dependency_overrides.clear()


def test_phase1_routes_are_unchanged(api):
    client, _ = api
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["phase"] == 1
    health = client.get("/api/health").json()
    assert set(health) == {"weather_cache", "model", "ready", "llm_status"}
    assert health["llm_status"] in {"ok", "fallback"}


def test_create_loan_uses_the_documented_defaults(api):
    client, fake = api
    created = client.post(
        "/api/loans",
        json={"borrower": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "principal_cents": 1000000},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["loan_id"] == 1
    assert body["tx_hash"].startswith("0x")
    assert body["limitations"]
    assert fake.created[0] == {
        "trigger": 13630,
        "rate": 1200,
        "term": 24,
        "max_reduction": 5000,
        "max_deferral": 4,
    }


def test_demo_2004_applies_relief_and_2005_does_not(api):
    client, fake = api
    dry = client.post("/api/demo/run", json={"year": 2004})
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["oracle"]["relief_applied"] is True
    assert body["oracle"]["tx_hash"].startswith("0x")
    assert body["oracle"]["evidence_hash"].startswith("0x")
    assert body["loan"]["create_tx_hash"].startswith("0x")
    assert body["loan"]["term_months"] == 24
    assert body["rainfall_line"]["uses_model_score"] is False
    assert body["weekly"]
    assert body["score_source"] == "leave_one_season_out"
    assert body["model_score"] is not None
    assert body["rule_score"] is not None
    assert body["limitations"]
    assert body["summary"]["payment_saved_first_relief_month_cents"] > 0
    assert body["schedule_after"][3]["payment_cents"] < body["schedule_before"][3]["payment_cents"]
    evidence = client.get("/api/evidence/" + body["oracle"]["evidence_hash"])
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["matches"] is True
    assert "model_score" not in evidence.json()["payload"]

    wet = client.post("/api/demo/run", json={"year": 2005})
    assert wet.status_code == 200, wet.text
    wet_body = wet.json()
    assert wet_body["oracle"]["relief_applied"] is False
    assert wet_body["oracle"]["tx_hash"] is None
    assert "No transaction was sent" in wet_body["oracle"]["reason"]
    assert wet_body["summary"]["extra_cost_cents"] == 0
    assert len(fake.loans[2]["history"]) == 0


def test_oracle_check_second_call_is_graceful_and_a_missing_loan_is_404(api):
    client, _ = api
    created = client.post(
        "/api/loans",
        json={"borrower": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC", "principal_cents": 1000000},
    )
    loan_id = created.json()["loan_id"]
    first = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2017})
    assert first.status_code == 200, first.text
    assert first.json()["relief_applied"] is True
    assert first.json()["schedule"]["summary"]["relief_months"] >= 24

    second = client.post(f"/api/oracle/check/{loan_id}", params={"season": 2017})
    assert second.status_code == 200, second.text
    assert second.json()["relief_applied"] is False
    assert "already applied" in second.json()["reason"]
    assert second.json()["schedule"] is None

    missing = client.get("/api/loans/99")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "LoanNotFound"


def test_other_reverts_are_409_and_a_stopped_node_is_503(api):
    client, fake = api

    def explode(loan_id):
        raise ChainRevert("NotOracle")

    fake.get_loan = explode
    denied = client.get("/api/loans/1")
    assert denied.status_code == 409
    assert denied.json()["detail"] == "NotOracle"

    fake.down = True
    down = client.post("/api/demo/run", json={"year": 2004})
    assert down.status_code == 503
    assert "chain node" in down.json()["detail"]

"""One API pass against a local Hardhat node. Skipped when the node or deployment is missing."""

import pytest

from chain.client import ChainUnavailable, LoanReliefClient

try:
    LoanReliefClient()
    SKIP = None
except ChainUnavailable as exc:
    SKIP = str(exc)

pytestmark = pytest.mark.skipif(SKIP is not None, reason=f"no local chain: {SKIP}")


def test_demo_2004_applies_and_2005_does_not():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    dry = client.post("/api/demo/run", json={"year": 2004})
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["oracle"]["relief_applied"] is True
    assert body["oracle"]["tx_hash"].startswith("0x")
    evidence = client.get("/api/evidence/" + body["oracle"]["evidence_hash"])
    assert evidence.status_code == 200
    assert evidence.json()["matches"] is True

    wet = client.post("/api/demo/run", json={"year": 2005})
    assert wet.status_code == 200, wet.text
    assert wet.json()["oracle"]["relief_applied"] is False
    assert wet.json()["oracle"]["tx_hash"] is None
    assert wet.json()["loan"]["id"] != body["loan"]["id"]

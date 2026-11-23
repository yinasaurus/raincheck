"""Runs against a LIVE local Hardhat node with the contract deployed. Skipped automatically otherwise.

  cd contracts && npx hardhat node                                   # terminal 1
  cd contracts && npx hardhat run scripts/deploy.ts --network localhost   # terminal 2
  cd backend && pytest tests/test_chain_integration.py
"""
import pytest

from chain.client import ChainRevert, ChainUnavailable, LoanReliefClient
from chain.evidence import build_evidence, hash_payload

try:
    CLIENT = LoanReliefClient()
    SKIP = None
except ChainUnavailable as exc:
    CLIENT, SKIP = None, str(exc)

pytestmark = pytest.mark.skipif(CLIENT is None, reason=f"no local chain: {SKIP}")

BORROWER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"  # Hardhat account #2 (public test address)
TRIGGER = 13630


def evidence(season, mm_total):
    p = build_evidence(region_name="Nueva Ecija", latitude=15.58, longitude=121.0, season_id=season,
                       daily_precip_mm=[(f"{season}-06-01", mm_total)], trigger_tenths_mm=TRIGGER,
                       fetched_at="2026-11-23T00:00:00Z")
    return hash_payload(p), p["season_total_tenths_mm"]


def new_loan():
    return CLIENT.create_loan(BORROWER, 100_000_00, 1200, 24, TRIGGER, 5000, 4)["loan_id"]


def test_full_relief_round_trip():
    loan_id = new_loan()
    h, observed = evidence(2004, 1244.0)
    res = CLIENT.apply_relief(loan_id, 2004, observed, "DEFERRAL", 2, h)
    assert res["tx_hash"].startswith("0x") and len(res["tx_hash"]) == 66
    hist = CLIENT.get_history(loan_id)
    assert len(hist) == 1 and hist[0]["reliefType"] == "DEFERRAL" and hist[0]["dataSourceHash"] == h
    assert CLIENT.get_loan(loan_id)["deferralUsedMonths"] == 2
    assert CLIENT.season_relieved(loan_id, 2004)


def test_rainfall_above_trigger_reverts_with_decoded_reason():
    loan_id = new_loan()
    h, observed = evidence(2005, 1500.0)
    with pytest.raises(ChainRevert) as e:
        CLIENT.apply_relief(loan_id, 2005, observed, "REDUCTION", 1000, h)
    assert e.value.error == "TriggerNotMet"
    assert CLIENT.get_history(loan_id) == []  # nothing was sent


def test_same_season_twice_reverts():
    loan_id = new_loan()
    h1, obs = evidence(2017, 1239.0)
    CLIENT.apply_relief(loan_id, 2017, obs, "REDUCTION", 1000, h1)
    h2, _ = evidence(2017, 1238.0)
    with pytest.raises(ChainRevert) as e:
        CLIENT.apply_relief(loan_id, 2017, obs, "REDUCTION", 1000, h2)
    assert e.value.error == "SeasonAlreadyRelieved"


def test_cap_exceeded_reverts():
    loan_id = new_loan()
    h, obs = evidence(2003, 1235.0)
    with pytest.raises(ChainRevert) as e:
        CLIENT.apply_relief(loan_id, 2003, obs, "REDUCTION", 5001, h)
    assert e.value.error == "ReductionCapExceeded"


def test_payment_and_missing_loan():
    loan_id = new_loan()
    CLIENT.record_payment(loan_id, 500_00)
    assert CLIENT.get_loan(loan_id)["paidCents"] == 500_00
    with pytest.raises(ChainRevert) as e:
        CLIENT.get_loan(9999)
    assert e.value.error == "LoanNotFound"

"""Oracle decision tests. Need the live local chain (see test_chain_integration.py); skipped otherwise."""
import json
from datetime import date

import pytest

from chain.client import ChainUnavailable, LoanReliefClient
from chain.oracle import check_and_apply, relief_from_history_row
from chain.schedule import before_and_after

try:
    CLIENT = LoanReliefClient()
    SKIP = None
except ChainUnavailable as exc:
    CLIENT, SKIP = None, str(exc)

pytestmark = pytest.mark.skipif(CLIENT is None, reason=f"no local chain: {SKIP}")
BORROWER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
TRIGGER = 13630


def season(year, total_mm):
    """Spread a season total over 100 days in exact tenths of a mm (Open-Meteo's precision)."""
    total_t = round(total_mm * 10)
    base, extra = divmod(total_t, 100)
    return [(f"{year}-{6 + i // 28:02d}-{i % 28 + 1:02d}", (base + (1 if i < extra else 0)) / 10) for i in range(100)]


def run(loan_id, year, total, tmp_path, **kw):
    return check_and_apply(CLIENT, loan_id=loan_id, season_id=year, daily_precip_mm=season(year, total),
                           region_name="Nueva Ecija", latitude=15.58, longitude=121.0,
                           fetched_at="2026-11-23T00:00:00Z", evidence_dir=tmp_path, **kw)


def new_loan():
    return CLIENT.create_loan(BORROWER, 100_000_00, 1200, 24, TRIGGER, 5000, 4)["loan_id"]


def test_dry_season_applies_relief_and_evidence_verifies(tmp_path):
    loan_id = new_loan()
    res = run(loan_id, 2004, 1244.0, tmp_path)
    assert res["relief_applied"] and res["tx_hash"].startswith("0x")
    stored = json.loads((tmp_path / f"{res['evidence_hash']}.json").read_text())
    assert stored["season_total_tenths_mm"] == 12440 and stored["below_trigger"] is True
    assert CLIENT.get_history(loan_id)[0]["dataSourceHash"] == res["evidence_hash"]


def test_wet_season_sends_no_transaction(tmp_path):
    loan_id = new_loan()
    res = run(loan_id, 2005, 1500.0, tmp_path)
    assert res["relief_applied"] is False and "tx_hash" not in res and "No transaction was sent" in res["reason"]
    assert CLIENT.get_history(loan_id) == []
    assert list(tmp_path.iterdir()) == []  # no evidence stored for a non-event


def test_rainfall_exactly_at_trigger_gets_no_relief(tmp_path):
    loan_id = new_loan()
    assert run(loan_id, 2006, 1363.0, tmp_path)["relief_applied"] is False


def test_second_check_same_season_is_graceful(tmp_path):
    loan_id = new_loan()
    assert run(loan_id, 2017, 1239.0, tmp_path)["relief_applied"]
    again = run(loan_id, 2017, 1239.0, tmp_path)
    assert again["relief_applied"] is False and "already applied" in again["reason"]
    assert len(CLIENT.get_history(loan_id)) == 1


def test_cap_exhausted_is_reported_not_crashed(tmp_path):
    loan_id = new_loan()
    assert run(loan_id, 2003, 1235.0, tmp_path, relief_value=5000)["relief_applied"]
    res = run(loan_id, 2004, 1244.0, tmp_path, relief_value=1000)
    assert res["relief_applied"] is False and "cap" in res["reason"]


def test_end_to_end_chain_event_drives_schedule(tmp_path):
    loan_id = new_loan()
    run(loan_id, 2004, 1244.0, tmp_path, relief_kind="DEFERRAL", relief_value=2)
    hist = CLIENT.get_history(loan_id)
    out = before_and_after(100_000_00, 1200, 24, date(2027, 1, 31), [relief_from_history_row(hist[0], 4)])
    assert len(out["before"]) == 24 and len(out["after"]) == 26
    assert out["summary"]["payment_saved_first_relief_month_cents"] > 0
    assert out["after"][-1]["balance_cents"] == 0

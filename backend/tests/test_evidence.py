"""Evidence JSON and the chain client's failure messages. No Hardhat node."""

import json

import pytest
from web3 import Web3

from chain.client import LOCAL_ORACLE_KEY, ChainClient, _error_name
from chain.errors import ChainUnavailable
from chain.evidence import (
    build_payload,
    canonical_bytes,
    keccak_hex,
    precip_text,
    read_evidence,
    save_evidence,
    tenths_to_mm_text,
    to_tenths_mm,
)


def _payload():
    return build_payload(
        region="Nueva Ecija",
        latitude=15.58,
        longitude=121.0,
        season_id=2004,
        season_rainfall_mm=1243.9,
        daily=[
            {"date": "2004-06-02", "precipitation_mm": 0.2},
            {"date": "2004-06-01", "precipitation_mm": None},
        ],
        data_source="Open-Meteo Archive API",
        source_url="https://archive-api.open-meteo.com/v1/archive",
        fetched_at="2026-11-23T04:23:29.898596+00:00",
        trigger_rainfall_tenths_mm=13630,
        loan_id=7,
        relief_type="REDUCTION",
        relief_value=3000,
        reduction_window_months=3,
    )


def test_tenths_use_half_up_and_do_not_follow_whole_millimetres():
    assert to_tenths_mm(1243.9) == 12439
    assert to_tenths_mm(1363) == 13630
    # 1362.6 mm rounds to 1363 whole millimetres in Phase 1, but is 13626 tenths.
    assert to_tenths_mm(1362.6) == 13626
    assert tenths_to_mm_text(13626) == "1362.6"
    assert precip_text(None) is None
    assert precip_text(0.2) == "0.20"


def test_canonical_json_is_sorted_and_the_hash_is_stable(tmp_path):
    payload = _payload()
    raw = canonical_bytes(payload)
    assert raw.startswith(b'{"comparison":')
    assert b": " not in raw
    assert b", " not in raw
    assert b"hash" not in raw
    parsed = json.loads(raw)
    assert parsed["daily_precipitation_mm"][0]["date"] == "2004-06-01"
    assert parsed["daily_precipitation_mm"][0]["precipitation_mm"] is None
    assert parsed["coordinates"] == {"latitude": "15.58", "longitude": "121.0"}
    assert parsed["season_rainfall_mm"] == "1243.9"
    first = keccak_hex(payload)
    second = save_evidence(payload, tmp_path)
    assert first == second
    stored = read_evidence(second, tmp_path)
    assert stored["matches"] is True
    assert stored["recomputed_hash"] == first
    assert stored["payload"]["loan_id"] == 7
    again = save_evidence(json.loads(raw), tmp_path)
    assert again == first


def test_custom_error_selector_decodes_without_a_node():
    name = "RainfallNotBelowTrigger"
    selector = Web3.keccak(text=f"{name}()")[:4]
    abi = [{"type": "error", "name": name, "inputs": []}]
    assert _error_name(abi, selector) == name


def test_a_stopped_node_is_reported_and_the_key_is_not_in_the_message(tmp_path):
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps({"address": "0x" + "11" * 20, "abi": []}), encoding="utf-8")
    client = ChainClient(
        rpc_url="http://127.0.0.1:1",
        private_key=LOCAL_ORACLE_KEY,
        deployment_path=deployment,
    )
    assert client._web3 is None
    with pytest.raises(ChainUnavailable) as caught:
        client.get_loan(1)
    assert "not running" in str(caught.value)
    assert LOCAL_ORACLE_KEY not in str(caught.value)
    assert client._private_key not in str(caught.value)

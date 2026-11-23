import json

from chain.evidence import (build_evidence, canonical_json, hash_payload, hex_to_bytes32, save_evidence,
                            to_tenths_mm, verify_evidence)

DAYS = [("2004-06-01", 0.0), ("2004-06-02", 12.4), ("2004-06-03", 3.1)]


def make(days=DAYS, trigger=13630):
    return build_evidence(region_name="Nueva Ecija", latitude=15.58, longitude=121.0, season_id=2004,
                          daily_precip_mm=days, trigger_tenths_mm=trigger, fetched_at="2026-11-23T00:00:00Z")


def test_tenths_conversion_avoids_float_noise():
    assert to_tenths_mm(0.1 + 0.2) == 3
    assert to_tenths_mm(12.4) == 124


def test_total_and_trigger_flag():
    p = make()
    assert p["season_total_tenths_mm"] == 0 + 124 + 31
    assert p["below_trigger"] is True
    assert make(trigger=155)["below_trigger"] is False  # equal is NOT below (strict rule)


def test_hash_is_stable_and_order_independent():
    assert hash_payload(make()) == hash_payload(make())
    assert hash_payload(make(DAYS)) == hash_payload(make(list(reversed(DAYS))))  # daily rows are sorted


def test_canonical_json_ignores_key_order_and_whitespace():
    assert canonical_json({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'


def test_any_change_changes_the_hash():
    base = hash_payload(make())
    changed = [("2004-06-01", 0.0), ("2004-06-02", 12.5), ("2004-06-03", 3.1)]
    assert hash_payload(make(changed)) != base
    assert hash_payload(make(trigger=13631)) != base


def test_hash_fits_bytes32():
    assert len(hex_to_bytes32(hash_payload(make()))) == 32


def test_save_and_verify_roundtrip(tmp_path):
    h, path = save_evidence(make(), tmp_path)
    assert path.name == f"{h}.json"
    res = verify_evidence(path)
    assert res["matches"] and res["recomputed_hash"] == h


def test_tampered_file_fails_verification(tmp_path):
    h, path = save_evidence(make(), tmp_path)
    data = json.loads(path.read_text())
    data["daily_precip_tenths_mm"][1][1] = 9999
    path.write_text(json.dumps(data))
    assert verify_evidence(path)["matches"] is False


def test_empty_rainfall_rejected():
    import pytest
    with pytest.raises(ValueError):
        make(days=[])

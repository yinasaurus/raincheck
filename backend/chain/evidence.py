"""Canonical evidence payloads and their keccak256 hashes.

The hash goes on-chain as `dataSourceHash`. Anyone can later fetch the stored payload, re-serialise it
canonically and recompute the hash. The chain proves WHAT evidence was submitted, not that the
weather data itself is true (the oracle problem).

Floats are avoided: daily rainfall is stored as integer tenths of a millimetre, the same unit the
contract uses, so serialisation is exact and identical everywhere.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from eth_utils import keccak

SCHEMA = "raincheck.evidence.v1"


def to_tenths_mm(mm: float) -> int:
    return int(round(mm * 10))


def canonical_json(obj) -> bytes:
    """Sorted keys, no whitespace, ASCII only: byte-for-byte reproducible."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def hash_payload(payload: dict) -> str:
    """0x-prefixed keccak256 hex of the canonical payload (fits bytes32)."""
    return "0x" + keccak(canonical_json(payload)).hex()


def build_evidence(
    *,
    region_name: str,
    latitude: float,
    longitude: float,
    season_id: int,
    daily_precip_mm: Iterable[tuple[str, float]],  # (ISO date, mm)
    trigger_tenths_mm: int,
    fetched_at: str,
    source: str = "Open-Meteo archive API (CC BY 4.0)",
) -> dict:
    daily = sorted((d, to_tenths_mm(mm)) for d, mm in daily_precip_mm)
    if not daily:
        raise ValueError("no daily rainfall supplied")
    total = sum(t for _, t in daily)
    return {
        "schema": SCHEMA,
        "region": {"name": region_name, "latitude": latitude, "longitude": longitude},
        "season_id": season_id,
        "source": source,
        "fetched_at": fetched_at,
        "daily_precip_tenths_mm": [[d, t] for d, t in daily],
        "season_total_tenths_mm": total,
        "trigger_tenths_mm": trigger_tenths_mm,
        "below_trigger": total < trigger_tenths_mm,  # strictly below, same rule as the contract
    }


def save_evidence(payload: dict, directory: str | Path) -> tuple[str, Path]:
    h = hash_payload(payload)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{h}.json"
    path.write_bytes(canonical_json(payload))
    return h, path


def verify_evidence(path: str | Path) -> dict:
    """Recompute the hash of a stored payload and compare with its filename."""
    path = Path(path)
    payload = json.loads(path.read_bytes())
    recomputed = hash_payload(payload)
    return {"claimed_hash": path.stem, "recomputed_hash": recomputed, "matches": recomputed == path.stem, "payload": payload}


def hex_to_bytes32(h: str) -> bytes:
    raw = bytes.fromhex(h[2:] if h.startswith("0x") else h)
    if len(raw) != 32:
        raise ValueError("expected 32 bytes")
    return raw

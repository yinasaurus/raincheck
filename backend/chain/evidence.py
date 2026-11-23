"""Canonical evidence for one relief decision.

The file is the JSON whose keccak256 is ``dataSourceHash`` on the contract.
The hash is not stored inside the JSON. Anyone can read the file, serialize
it the same way, and check the hash.

Daily rainfall is a fixed two-decimal string. A missing day stays JSON null.
The season total compared with the trigger is the season sum, converted to
tenths of a millimetre half-up, not the sum of each day rounded on its own.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from web3 import Web3

from data.paths import BACKEND_ROOT, CACHE_META

EVIDENCE_DIR = BACKEND_ROOT / "data" / "evidence"


def to_tenths_mm(millimetres: float) -> int:
    """Convert a millimetre amount to tenths, half-up. 1363.0 mm is 13630."""
    number = Decimal(str(millimetres))
    if not number.is_finite() or number < 0:
        raise ValueError("rainfall must be a non-negative number")
    return int((number * 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tenths_to_mm_text(tenths: int) -> str:
    """One decimal place, taken from the integer the contract compares."""
    if tenths < 0:
        raise ValueError("tenths cannot be negative")
    return f"{tenths // 10}.{tenths % 10}"


def precip_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        return None
    return f"{number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def keccak_hex(payload: dict) -> str:
    """Lowercase hex with a 0x prefix."""
    digest = Web3.keccak(canonical_bytes(payload))
    text = digest.hex()
    return text if text.startswith("0x") else "0x" + text


def build_payload(
    *,
    region: str,
    latitude,
    longitude,
    season_id: int,
    season_rainfall_mm: float,
    daily: list[dict],
    data_source: str,
    source_url: str,
    fetched_at: str,
    trigger_rainfall_tenths_mm: int,
    loan_id: int,
    relief_type: str,
    relief_value: int,
    reduction_window_months: int,
) -> dict:
    kind = relief_type.upper()
    if kind not in {"REDUCTION", "DEFERRAL"}:
        raise ValueError("relief_type must be REDUCTION or DEFERRAL")
    return {
        "region": region,
        "coordinates": {
            "latitude": format(Decimal(str(latitude)), "f"),
            "longitude": format(Decimal(str(longitude)), "f"),
        },
        "season_id": int(season_id),
        "season_rainfall_mm": tenths_to_mm_text(to_tenths_mm(season_rainfall_mm)),
        "season_rainfall_tenths_mm": to_tenths_mm(season_rainfall_mm),
        "daily_precipitation_mm": [
            {"date": row["date"], "precipitation_mm": precip_text(row["precipitation_mm"])}
            for row in sorted(daily, key=lambda row: row["date"])
        ],
        "data_source": data_source,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "trigger_rainfall_tenths_mm": int(trigger_rainfall_tenths_mm),
        "comparison": "strictly_below",
        "loan_id": int(loan_id),
        "relief": {
            "type": kind,
            "value": int(relief_value),
            "reduction_window_months": int(reduction_window_months) if kind == "REDUCTION" else 0,
        },
    }


def load_cache_source() -> dict:
    meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
    return {
        "data_source": str(meta.get("source") or "Open-Meteo Archive API"),
        "source_url": str(meta.get("url") or ""),
        "fetched_at": str(meta.get("fetched_at") or ""),
        "license": str(meta.get("license_note") or "Open-Meteo data is published under CC-BY 4.0."),
    }


def save_evidence(payload: dict, directory: Path | None = None) -> str:
    """Write canonical JSON to data/evidence/<hash>.json and return the 0x hash."""
    raw = canonical_bytes(payload)
    digest = Web3.keccak(raw)
    text = digest.hex()
    hex_hash = text if text.startswith("0x") else "0x" + text
    folder = directory or EVIDENCE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{hex_hash[2:]}.json").write_bytes(raw)
    return hex_hash


def read_evidence(hex_hash: str, directory: Path | None = None) -> dict:
    """Return the stored payload and a hash recomputed from those bytes."""
    token = hex_hash[2:] if hex_hash.startswith("0x") else hex_hash
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise ValueError("evidence hash must be 32 bytes of hex")
    path = (directory or EVIDENCE_DIR) / f"{token.lower()}.json"
    if not path.exists():
        raise FileNotFoundError(token.lower())
    payload = json.loads(path.read_text(encoding="utf-8"))
    recomputed = keccak_hex(payload)
    return {
        "hash": "0x" + token.lower(),
        "recomputed_hash": recomputed,
        "matches": recomputed == "0x" + token.lower(),
        "payload": payload,
    }

"""The oracle decision: look at observed season rainfall, and ONLY if it is strictly below the loan's
trigger build evidence, hash it, and call applyRelief on-chain. Otherwise send nothing.

The AI/ML score is deliberately NOT an input here. Relief is triggered by observed rainfall alone.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .client import ChainRevert, LoanReliefClient
from .evidence import build_evidence, save_evidence
from .schedule import Relief


def check_and_apply(
    client: LoanReliefClient,
    *,
    loan_id: int,
    season_id: int,
    daily_precip_mm: Iterable[tuple[str, float]],
    region_name: str,
    latitude: float,
    longitude: float,
    fetched_at: str,
    evidence_dir: str | Path,
    relief_kind: str = "REDUCTION",
    relief_value: int = 3000,  # bps for REDUCTION, months for DEFERRAL
) -> dict:
    loan = client.get_loan(loan_id)  # raises ChainRevert(LoanNotFound) for unknown loans
    trigger = int(loan["triggerRainfallTenthsMm"])
    payload = build_evidence(
        region_name=region_name, latitude=latitude, longitude=longitude, season_id=season_id,
        daily_precip_mm=daily_precip_mm, trigger_tenths_mm=trigger, fetched_at=fetched_at,
    )
    total = payload["season_total_tenths_mm"]
    base = {
        "loan_id": loan_id,
        "season_id": season_id,
        "season_total_mm": total / 10,
        "trigger_mm": trigger / 10,
        "relief_applied": False,
    }

    if not payload["below_trigger"]:
        return {**base, "reason": (f"No relief: season rainfall {total / 10:.1f} mm is not below the "
                                   f"trigger of {trigger / 10:.1f} mm. No transaction was sent.")}

    evidence_hash, _ = save_evidence(payload, evidence_dir)
    try:
        sent = client.apply_relief(loan_id, season_id, total, relief_kind, relief_value, evidence_hash)
    except ChainRevert as exc:
        if exc.error in ("SeasonAlreadyRelieved", "EvidenceAlreadyUsed"):
            return {**base, "evidence_hash": evidence_hash,
                    "reason": f"Relief was already applied for season {season_id} on this loan ({exc.error})."}
        if exc.error in ("ReductionCapExceeded", "DeferralCapExceeded"):
            return {**base, "evidence_hash": evidence_hash,
                    "reason": f"Trigger met but the loan's relief cap is used up ({exc.error})."}
        raise
    return {**base, "relief_applied": True, "relief_kind": relief_kind, "relief_value": relief_value,
            "evidence_hash": evidence_hash, "tx_hash": sent["tx_hash"], "block_number": sent["block_number"],
            "reason": f"Season rainfall {total / 10:.1f} mm is below the trigger of {trigger / 10:.1f} mm."}


def relief_from_history_row(row: dict, start_month: int, reduction_window: int = 3) -> Relief:
    """Turn an on-chain relief event into a schedule Relief starting at a given installment."""
    return Relief(row["reliefType"], int(row["reliefValue"]), start_month, reduction_window)

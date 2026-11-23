"""Loan, oracle, and demo routes.

These routes call the local contract. They do not change the Phase 1 risk
routes. A model score is never sent to the contract. If the node is down the
response is HTTP 503 and no result is invented.

POST /api/demo/run response shape (stable for the demo UI):

- year, limitations, units
- weekly: the same week rows as POST /api/simulate
- season_rainfall_mm, season_rainfall_tenths_mm
- model_score, rule_score, score_source, score_week (last week that was scored, not carried forward)
- trigger: the Phase 1 whole-millimetre trigger object
- chain_trigger: tenths compared on chain, strictly below
- loan: id, create_tx_hash, and the terms just written
- relief: applied, type, value, reduction_window_months, tx_hash, evidence_hash, message
- schedule_before, schedule_after, summary
- comparison_note
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.service import LIMITATIONS, NotReady, SeasonNotFound
from chain.client import ChainClient
from chain.errors import ChainRevert, ChainUnavailable
from chain.evidence import (
    build_payload,
    load_cache_source,
    read_evidence,
    save_evidence,
    tenths_to_mm_text,
    to_tenths_mm,
)
from chain.schedule import build_schedules
from data.aggregate import season_bounds

router = APIRouter()

UNITS = {
    "money": "cents of a demo currency (100 cents = 1.00). Not legal tender.",
    "rate": "basis points (10000 = 100%)",
    "rainfall": "The contract stores tenths of a millimetre. 1363.0 mm is 13630.",
}
REDUCTION_WINDOW_MONTHS = 3
DEMO_BORROWER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
DEMO_PRINCIPAL_CENTS = 5_000_000
DEMO_RATE_BPS = 1200
DEMO_TERM_MONTHS = 12
DEMO_MAX_REDUCTION_BPS = 3000
DEMO_MAX_DEFERRAL_MONTHS = 2
COMPARISON_NOTE = (
    "Held-out model score versus the 75% rainfall rule versus the pre-agreed rainfall line. "
    "A payment change depends only on the rainfall line. The model score does not change what is owed."
)
ALREADY_APPLIED = {"ReliefAlreadyAppliedForSeason", "DuplicateEvidence"}


class LoanBody(BaseModel):
    borrower: str
    principal_cents: int = Field(..., gt=0)
    annual_rate_bps: int = Field(..., ge=0, le=10000)
    term_months: int = Field(..., ge=1, le=600)
    trigger_rainfall_mm: float | None = Field(
        default=None,
        gt=0,
        description="Defaults to the project's payment line (80% of the long-term average, 1363 mm on this cache).",
    )
    max_reduction_bps: int = Field(3000, ge=0, le=10000)
    max_deferral_months: int = Field(2, ge=0, le=600)


class DemoBody(BaseModel):
    year: int = Field(..., ge=1900, le=2100, examples=[2004])


def get_chain() -> ChainClient:
    return ChainClient()


def get_service():
    from app.main import service

    return service


def no_relief_message(observed_tenths: int, trigger_tenths: int) -> str | None:
    """None when the contract would accept the rainfall. Wording matches the demo."""
    if observed_tenths < trigger_tenths:
        return None
    observed = tenths_to_mm_text(observed_tenths)
    trigger = tenths_to_mm_text(trigger_tenths)
    relation = "not below" if observed_tenths == trigger_tenths else "above"
    return f"no relief: season rainfall {observed} mm is {relation} the trigger {trigger} mm"


@router.post("/api/loans")
def create_loan(body: LoanBody, chain: ChainClient = Depends(get_chain), service=Depends(get_service)) -> dict:
    if not _is_address(body.borrower):
        raise HTTPException(status_code=400, detail="borrower must be a 20-byte hex address.")
    trigger = _trigger_tenths(body.trigger_rainfall_mm, service)
    created = _chain(lambda: chain.create_loan(
        body.borrower,
        body.principal_cents,
        body.annual_rate_bps,
        body.term_months,
        trigger,
        body.max_reduction_bps,
        body.max_deferral_months,
    ))
    return {
        **created,
        "trigger_rainfall_tenths_mm": trigger,
        "trigger_rainfall_mm": tenths_to_mm_text(trigger),
        "units": UNITS,
        "limitations": LIMITATIONS,
    }


@router.get("/api/loans/{loan_id}")
def get_loan(
    loan_id: int,
    first_payment: date | None = Query(default=None),
    chain: ChainClient = Depends(get_chain),
) -> dict:
    loan = _chain(lambda: chain.get_loan(loan_id))
    history = _chain(lambda: chain.get_history(loan_id))
    anchor = first_payment or _anchor_from_history(history)
    window, window_source = _window_from_history(history)
    schedules = build_schedules(
        loan["principal_cents"],
        loan["annual_rate_bps"],
        loan["term_months"],
        _events(history),
        reduction_window_months=window,
        first_payment=anchor,
    )
    schedules["summary"]["reduction_window_source"] = window_source
    return {
        "loan": loan,
        "relief_history": history,
        **schedules,
        "units": UNITS,
        "limitations": LIMITATIONS,
    }


@router.post("/api/oracle/check/{loan_id}")
def oracle_check(
    loan_id: int,
    season: int = Query(..., ge=1900, le=2100),
    chain: ChainClient = Depends(get_chain),
    service=Depends(get_service),
) -> dict:
    loan = _chain(lambda: chain.get_loan(loan_id))
    simulated = _simulate(service, season)
    observed = to_tenths_mm(simulated["season_rainfall_mm"])
    trigger = int(loan["trigger_rainfall_tenths_mm"])
    blocked = no_relief_message(observed, trigger)
    if blocked:
        return _check_body(loan, season, simulated, observed, applied=False, message=blocked, chain=chain)
    kind, value = _relief_choice(loan)
    evidence_hash = _write_evidence(service, loan_id, season, simulated["season_rainfall_mm"], trigger, kind, value)
    try:
        sent = chain.apply_relief(loan_id, observed, kind, value, evidence_hash, season)
    except ChainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ChainRevert as exc:
        if str(exc) in ALREADY_APPLIED:
            raise HTTPException(
                status_code=409,
                detail={
                    "applied": False,
                    "reason": "already_applied",
                    "message": "Relief was already applied for this loan and season.",
                    "evidence_hash": evidence_hash,
                },
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _check_body(
        loan,
        season,
        simulated,
        observed,
        applied=True,
        message="Relief applied.",
        chain=chain,
        tx_hash=sent["tx_hash"],
        evidence_hash=evidence_hash,
        relief_type=kind,
        relief_value=value,
    )


@router.get("/api/evidence/{evidence_hash}")
def get_evidence(evidence_hash: str) -> dict:
    try:
        body = read_evidence(evidence_hash)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No evidence file for that hash.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    body["limitations"] = LIMITATIONS
    return body


@router.post("/api/demo/run")
def demo_run(body: DemoBody, chain: ChainClient = Depends(get_chain), service=Depends(get_service)) -> dict:
    simulated = _simulate(service, body.year)
    trigger = int(service.trigger_mm) * 10
    created = _chain(lambda: chain.create_loan(
        DEMO_BORROWER,
        DEMO_PRINCIPAL_CENTS,
        DEMO_RATE_BPS,
        DEMO_TERM_MONTHS,
        trigger,
        DEMO_MAX_REDUCTION_BPS,
        DEMO_MAX_DEFERRAL_MONTHS,
    ))
    observed = to_tenths_mm(simulated["season_rainfall_mm"])
    relief = {
        "applied": False,
        "type": None,
        "value": None,
        "reduction_window_months": REDUCTION_WINDOW_MONTHS,
        "tx_hash": None,
        "evidence_hash": None,
        "message": None,
    }
    events: list[dict] = []
    blocked = no_relief_message(observed, trigger)
    if blocked:
        relief["message"] = blocked
    else:
        evidence_hash = _write_evidence(
            service,
            created["loan_id"],
            body.year,
            simulated["season_rainfall_mm"],
            trigger,
            "REDUCTION",
            DEMO_MAX_REDUCTION_BPS,
        )
        try:
            sent = chain.apply_relief(
                created["loan_id"],
                observed,
                "REDUCTION",
                DEMO_MAX_REDUCTION_BPS,
                evidence_hash,
                body.year,
            )
        except ChainUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ChainRevert as exc:
            if str(exc) not in ALREADY_APPLIED:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            relief["evidence_hash"] = evidence_hash
            relief["message"] = "Relief was already applied for this loan and season. No new transaction was sent."
        else:
            relief.update(
                {
                    "applied": True,
                    "type": "REDUCTION",
                    "value": DEMO_MAX_REDUCTION_BPS,
                    "tx_hash": sent["tx_hash"],
                    "evidence_hash": evidence_hash,
                    "message": "Relief applied.",
                }
            )
            events.append({"type": "REDUCTION", "value": DEMO_MAX_REDUCTION_BPS})
    schedules = build_schedules(
        DEMO_PRINCIPAL_CENTS,
        DEMO_RATE_BPS,
        DEMO_TERM_MONTHS,
        events,
        reduction_window_months=REDUCTION_WINDOW_MONTHS,
        first_payment=date(body.year, 11, 1),
    )
    scored = [
        week
        for week in simulated["weeks"]
        if week["risk_score"] is not None and not week["risk_carried_forward"]
    ]
    last = scored[-1] if scored else None
    return {
        "year": body.year,
        "limitations": LIMITATIONS,
        "units": UNITS,
        "weekly": simulated["weeks"],
        "season_rainfall_mm": simulated["season_rainfall_mm"],
        "season_rainfall_tenths_mm": observed,
        "model_score": None if last is None else last["risk_score"],
        "rule_score": None if last is None else last["baseline_score"],
        "score_source": None if last is None else last["score_source"],
        "score_week": None if last is None else last["week_index"],
        "trigger": simulated["trigger"],
        "chain_trigger": {
            "trigger_rainfall_tenths_mm": trigger,
            "observed_rainfall_tenths_mm": observed,
            "fired": observed < trigger,
            "comparison": "strictly_below",
        },
        "loan": {
            "id": created["loan_id"],
            "create_tx_hash": created["tx_hash"],
            "borrower": DEMO_BORROWER,
            "principal_cents": DEMO_PRINCIPAL_CENTS,
            "annual_rate_bps": DEMO_RATE_BPS,
            "term_months": DEMO_TERM_MONTHS,
            "max_reduction_bps": DEMO_MAX_REDUCTION_BPS,
            "max_deferral_months": DEMO_MAX_DEFERRAL_MONTHS,
        },
        "relief": relief,
        "schedule_before": schedules["schedule_before"],
        "schedule_after": schedules["schedule_after"],
        "summary": schedules["summary"],
        "comparison_note": COMPARISON_NOTE,
    }


def _check_body(
    loan: dict,
    season: int,
    simulated: dict,
    observed: int,
    applied: bool,
    message: str,
    chain: ChainClient,
    tx_hash: str | None = None,
    evidence_hash: str | None = None,
    relief_type: str | None = None,
    relief_value: int | None = None,
) -> dict:
    history = chain.get_history(loan["loan_id"])
    window, window_source = _window_from_history(history)
    schedules = build_schedules(
        loan["principal_cents"],
        loan["annual_rate_bps"],
        loan["term_months"],
        _events(history),
        reduction_window_months=window,
        first_payment=date(season, 11, 1),
    )
    schedules["summary"]["reduction_window_source"] = window_source
    return {
        "loan_id": loan["loan_id"],
        "season": season,
        "applied": applied,
        "relief_type": relief_type,
        "relief_value": relief_value,
        "reduction_window_months": window,
        "tx_hash": tx_hash,
        "evidence_hash": evidence_hash,
        "message": message,
        "season_rainfall_mm": simulated["season_rainfall_mm"],
        "season_rainfall_tenths_mm": observed,
        "trigger_rainfall_tenths_mm": loan["trigger_rainfall_tenths_mm"],
        "trigger": simulated["trigger"],
        **schedules,
        "units": UNITS,
        "limitations": LIMITATIONS,
    }


def _write_evidence(service, loan_id: int, season: int, rainfall_mm: float, trigger: int, kind: str, value: int) -> str:
    source = load_cache_source()
    payload = build_payload(
        region=service.region["name"],
        latitude=service.region["latitude"],
        longitude=service.region["longitude"],
        season_id=season,
        season_rainfall_mm=rainfall_mm,
        daily=_season_daily(service, season),
        data_source=source["data_source"],
        source_url=source["source_url"],
        fetched_at=source["fetched_at"],
        trigger_rainfall_tenths_mm=trigger,
        loan_id=loan_id,
        relief_type=kind,
        relief_value=value,
        reduction_window_months=REDUCTION_WINDOW_MONTHS,
    )
    payload["license"] = source["license"]
    return save_evidence(payload)


def _season_daily(service, year: int) -> list[dict]:
    start, end = season_bounds(year, service.months)
    frame = service.daily
    selected = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))]
    rows = []
    for record in selected.itertuples(index=False):
        when = record.date
        iso = when.date().isoformat() if hasattr(when, "date") else str(when)[:10]
        value = record.precipitation_mm
        rows.append({"date": iso, "precipitation_mm": None if pd.isna(value) else float(value)})
    return rows


def _relief_choice(loan: dict) -> tuple[str, int]:
    if int(loan["max_reduction_bps"]) > 0:
        return "REDUCTION", int(loan["max_reduction_bps"])
    if int(loan["max_deferral_months"]) > 0:
        return "DEFERRAL", int(loan["max_deferral_months"])
    raise ValueError("This loan has no reduction or deferral room, so no transaction was sent.")


def _trigger_tenths(trigger_rainfall_mm: float | None, service) -> int:
    if trigger_rainfall_mm is None:
        service.require_weather()
        return int(service.trigger_mm) * 10
    return to_tenths_mm(trigger_rainfall_mm)


def _simulate(service, year: int) -> dict:
    try:
        simulated = service.simulate(year)
    except NotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SeasonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if simulated["season_rainfall_mm"] is None:
        raise HTTPException(status_code=400, detail=f"Season {year} is incomplete, so relief is not evaluated.")
    return simulated


def _events(history: list[dict]) -> list[dict]:
    return [{"type": row["relief_type"], "value": row["relief_value"]} for row in history]


def _window_from_history(history: list[dict]) -> tuple[int, str]:
    for row in history:
        if row["relief_type"] != "REDUCTION":
            continue
        try:
            stored = read_evidence(row["data_source_hash"])
            window = int(stored["payload"]["relief"]["reduction_window_months"])
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            continue
        if window > 0:
            return window, "evidence"
    return REDUCTION_WINDOW_MONTHS, "default"


def _anchor_from_history(history: list[dict]) -> date:
    if history:
        return date(int(history[-1]["season_id"]), 11, 1)
    return date(date.today().year, 11, 1)


def _is_address(value: str) -> bool:
    return value.startswith("0x") and len(value) == 42 and all(char in "0123456789abcdefABCDEF" for char in value[2:])


def _chain(func):
    try:
        return func()
    except ChainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ChainRevert as exc:
        if str(exc) == "LoanNotFound":
            raise HTTPException(status_code=404, detail="No loan with that id.") from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

"""Loan, oracle, and demo routes.

These call backend/chain. They do not score weather and they do not change the
Phase 1 routes. A model score is never passed to the oracle.

POST /api/demo/run response shape (stable):

- year, limitations
- weekly: the same week rows as POST /api/simulate
- model_score, rule_score, score_source, score_week
- rainfall_line: the Phase 1 whole-millimetre trigger (uses_model_score is false)
- loan: id, create_tx_hash, and the terms written for this call
- oracle: the check_and_apply result. tx_hash and evidence_hash are null when no relief transaction was sent
- schedule_before, schedule_after, summary: chain.schedule.before_and_after
- comparison_note

The first relief event is applied from installment 4. A later event starts on the
installment after the previous relief window. The first due date is 1 November
of the replayed year.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.service import LIMITATIONS, NotReady, SeasonNotFound
from chain.client import ChainRevert, ChainUnavailable, LoanReliefClient
from chain.evidence import verify_evidence
from chain.oracle import check_and_apply, relief_from_history_row
from chain.schedule import before_and_after
from data.aggregate import season_bounds
from data.paths import BACKEND_ROOT, CACHE_META

router = APIRouter()

EVIDENCE_DIR = BACKEND_ROOT / "data" / "evidence"
DEMO_BORROWER = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
DEMO_PRINCIPAL_CENTS = 10_000_000
DEFAULT_TRIGGER_TENTHS = 13630
DEFAULT_RATE_BPS = 1200
DEFAULT_TERM_MONTHS = 24
DEFAULT_MAX_REDUCTION_BPS = 5000
DEFAULT_MAX_DEFERRAL_MONTHS = 4
DEFAULT_RELIEF_START_MONTH = 4
COMPARISON_NOTE = (
    "Held-out model score versus the 75% rainfall rule versus the pre-agreed rainfall line. "
    "A payment change depends only on observed season rainfall. The model score is not sent to the oracle."
)


class LoanBody(BaseModel):
    borrower: str
    principal_cents: int = Field(..., gt=0)
    annual_rate_bps: int = Field(DEFAULT_RATE_BPS, ge=0, le=10000)
    term_months: int = Field(DEFAULT_TERM_MONTHS, ge=1, le=600)
    trigger_rainfall_tenths_mm: int = Field(DEFAULT_TRIGGER_TENTHS, gt=0)
    max_reduction_bps: int = Field(DEFAULT_MAX_REDUCTION_BPS, ge=0, le=10000)
    max_deferral_months: int = Field(DEFAULT_MAX_DEFERRAL_MONTHS, ge=0)


class DemoBody(BaseModel):
    year: int = Field(..., ge=1900, le=2100, examples=[2004])


def get_client() -> LoanReliefClient:
    try:
        return LoanReliefClient()
    except ChainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def get_service():
    from app.main import service

    return service


@router.post("/api/loans")
def create_loan(body: LoanBody, client: LoanReliefClient = Depends(get_client)) -> dict:
    if not _is_address(body.borrower):
        raise HTTPException(status_code=400, detail="borrower must be a 20-byte hex address.")
    created = _chain(lambda: client.create_loan(
        body.borrower,
        body.principal_cents,
        body.annual_rate_bps,
        body.term_months,
        body.trigger_rainfall_tenths_mm,
        body.max_reduction_bps,
        body.max_deferral_months,
    ))
    return {
        "loan_id": created["loan_id"],
        "tx_hash": created["tx_hash"],
        "limitations": LIMITATIONS,
    }


@router.get("/api/loans/{loan_id}")
def get_loan(loan_id: int, client: LoanReliefClient = Depends(get_client)) -> dict:
    loan = _chain(lambda: client.get_loan(loan_id))
    history = _chain(lambda: client.get_history(loan_id))
    schedules = _schedules(loan, history)
    return {
        "loan": _jsonable(loan),
        "relief_history": [_jsonable(row) for row in history],
        "relief_start_month": DEFAULT_RELIEF_START_MONTH,
        **schedules,
        "limitations": LIMITATIONS,
    }


@router.post("/api/oracle/check/{loan_id}")
def oracle_check(
    loan_id: int,
    season: int = Query(..., ge=1900, le=2100),
    client: LoanReliefClient = Depends(get_client),
    service=Depends(get_service),
) -> dict:
    result = _chain(lambda: check_and_apply(
        client,
        loan_id=loan_id,
        season_id=season,
        daily_precip_mm=_season_daily(service, season),
        region_name=service.region["name"],
        latitude=float(service.region["latitude"]),
        longitude=float(service.region["longitude"]),
        fetched_at=_fetched_at(),
        evidence_dir=EVIDENCE_DIR,
    ))
    body = _oracle_body(result)
    body["limitations"] = LIMITATIONS
    if result.get("relief_applied"):
        loan = _chain(lambda: client.get_loan(loan_id))
        history = _chain(lambda: client.get_history(loan_id))
        body["schedule"] = _schedules(loan, history, season)
    else:
        body["schedule"] = None
    return body


@router.get("/api/evidence/{evidence_hash}")
def get_evidence(evidence_hash: str) -> dict:
    path = _evidence_path(evidence_hash)
    if path is None:
        raise HTTPException(status_code=404, detail="No evidence file for that hash.")
    try:
        checked = verify_evidence(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    checked["limitations"] = LIMITATIONS
    return checked


@router.post("/api/demo/run")
def demo_run(body: DemoBody, client: LoanReliefClient = Depends(get_client), service=Depends(get_service)) -> dict:
    simulated = _simulate(service, body.year)
    created = _chain(lambda: client.create_loan(
        DEMO_BORROWER,
        DEMO_PRINCIPAL_CENTS,
        DEFAULT_RATE_BPS,
        DEFAULT_TERM_MONTHS,
        DEFAULT_TRIGGER_TENTHS,
        DEFAULT_MAX_REDUCTION_BPS,
        DEFAULT_MAX_DEFERRAL_MONTHS,
    ))
    result = _chain(lambda: check_and_apply(
        client,
        loan_id=created["loan_id"],
        season_id=body.year,
        daily_precip_mm=_season_daily(service, body.year),
        region_name=service.region["name"],
        latitude=float(service.region["latitude"]),
        longitude=float(service.region["longitude"]),
        fetched_at=_fetched_at(),
        evidence_dir=EVIDENCE_DIR,
    ))
    loan = _chain(lambda: client.get_loan(created["loan_id"]))
    history = _chain(lambda: client.get_history(created["loan_id"]))
    scored = [
        week
        for week in simulated["weeks"]
        if week["risk_score"] is not None and not week["risk_carried_forward"]
    ]
    last = scored[-1] if scored else None
    return {
        "year": body.year,
        "limitations": LIMITATIONS,
        "weekly": simulated["weeks"],
        "model_score": None if last is None else last["risk_score"],
        "rule_score": None if last is None else last["baseline_score"],
        "score_source": None if last is None else last["score_source"],
        "score_week": None if last is None else last["week_index"],
        "rainfall_line": simulated["trigger"],
        "loan": {
            "id": created["loan_id"],
            "create_tx_hash": created["tx_hash"],
            "borrower": DEMO_BORROWER,
            "principal_cents": DEMO_PRINCIPAL_CENTS,
            "annual_rate_bps": DEFAULT_RATE_BPS,
            "term_months": DEFAULT_TERM_MONTHS,
            "trigger_rainfall_tenths_mm": DEFAULT_TRIGGER_TENTHS,
            "max_reduction_bps": DEFAULT_MAX_REDUCTION_BPS,
            "max_deferral_months": DEFAULT_MAX_DEFERRAL_MONTHS,
        },
        "oracle": _oracle_body(result),
        **_schedules(loan, history, body.year),
        "comparison_note": COMPARISON_NOTE,
    }


def _schedules(loan: dict, history: list[dict], season_year: int | None = None) -> dict:
    first_due = date(season_year or date.today().year, 11, 1)
    if history:
        first_due = date(int(history[0]["seasonId"]), 11, 1)
    built = before_and_after(
        int(loan["principalCents"]),
        int(loan["annualRateBps"]),
        int(loan["termMonths"]),
        first_due,
        _reliefs(history),
    )
    return {
        "schedule_before": built["before"],
        "schedule_after": built["after"],
        "summary": built["summary"],
    }


def _reliefs(history: list[dict]):
    start = DEFAULT_RELIEF_START_MONTH
    reliefs = []
    for row in history:
        relief = relief_from_history_row(row, start)
        reliefs.append(relief)
        start += relief.length()
    return reliefs


def _oracle_body(result: dict) -> dict:
    body = _jsonable(result)
    body.setdefault("tx_hash", None)
    body.setdefault("evidence_hash", None)
    return body


def _season_daily(service, year: int) -> list[tuple[str, float]]:
    service.require_weather()
    if year not in service.buckets and (
        service.labeled is None or service.labeled[service.labeled["year"] == year].empty
    ):
        raise SeasonNotFound(f"No weather for {year} in the cache.")
    start, end = season_bounds(year, service.months)
    frame = service.daily
    selected = frame[(frame["date"] >= pd.Timestamp(start)) & (frame["date"] <= pd.Timestamp(end))]
    rows = []
    for record in selected.itertuples(index=False):
        when = record.date
        iso = when.date().isoformat() if hasattr(when, "date") else str(when)[:10]
        value = record.precipitation_mm
        millimetres = 0.0 if pd.isna(value) else float(value)
        rows.append((iso, millimetres))
    if not rows:
        raise SeasonNotFound(f"No daily rainfall for {year} in the cache.")
    return rows


def _fetched_at() -> str:
    meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
    return str(meta.get("fetched_at") or "")


def _simulate(service, year: int) -> dict:
    try:
        simulated = service.simulate(year)
    except NotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SeasonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return simulated


def _evidence_path(evidence_hash: str):
    token = evidence_hash[2:] if evidence_hash.startswith("0x") else evidence_hash
    if len(token) != 64 or any(char not in "0123456789abcdefABCDEF" for char in token):
        raise HTTPException(status_code=400, detail="evidence hash must be 32 bytes of hex.")
    for name in (f"0x{token.lower()}.json", f"{token.lower()}.json"):
        path = EVIDENCE_DIR / name
        if path.exists():
            return path
    return None


def _is_address(value: str) -> bool:
    return value.startswith("0x") and len(value) == 42 and all(char in "0123456789abcdefABCDEF" for char in value[2:])


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if hasattr(value, "item"):
        return value.item()
    return value


def _chain(func):
    try:
        return func()
    except ChainUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ChainRevert as exc:
        status = 404 if exc.error == "LoanNotFound" else 409
        raise HTTPException(status_code=status, detail=exc.error) from exc
    except SeasonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

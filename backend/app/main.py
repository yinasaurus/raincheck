"""RainCheck API.

Phase 1 routes score rainfall. Loan routes talk to the local contract.
The risk score is advice and is not an input to relief.
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.service import NotReady, RainCheckService, SeasonNotFound

app = FastAPI(
    title="RainCheck",
    summary="Weather-adaptive loan prototype. Phase 1: rainfall risk, not the loan contract.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

service = RainCheckService()


class SimulateBody(BaseModel):
    year: int = Field(..., ge=1900, le=2100, examples=[2015])


_DEPRECATED_SCORE = "Deprecated. Use p_relief."
_DEPRECATED_BASELINE = "Deprecated. Use rule_score."


class RiskOut(BaseModel):
    """Documented fields only. Extra keys on the live response are kept."""

    model_config = ConfigDict(extra="allow")
    risk_score: float | None = Field(None, deprecated=True, description=_DEPRECATED_SCORE)
    baseline_score: float | None = Field(None, deprecated=True, description=_DEPRECATED_BASELINE)
    p_relief: float | None = None
    rule_score: float | None = None


class SimulateWeekOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    risk_score: float | None = Field(None, deprecated=True, description=_DEPRECATED_SCORE)
    baseline_score: float | None = Field(None, deprecated=True, description=_DEPRECATED_BASELINE)
    p_relief: float | None = None
    rule_score: float | None = None


class SimulateOut(BaseModel):
    model_config = ConfigDict(extra="allow")
    p_relief: float | None = None
    rule_score: float | None = None
    weeks: list[SimulateWeekOut] = Field(default_factory=list)


@app.get("/")
def root() -> dict:
    return {
        "name": "RainCheck",
        "phase": 1,
        "docs": "/docs",
        "advisory_only": True,
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "weather_cache": service.daily is not None,
        "model": service.bundle is not None,
        "ready": service.daily is not None and service.bundle is not None,
    }


@app.get("/api/region")
def region() -> dict:
    return _call(service.region_payload)


@app.get("/api/weather/observed")
def observed_weather(
    start: date = Query(..., alias="from"),
    end: date = Query(..., alias="to"),
    resolution: str = Query("weekly"),
) -> dict:
    return _call(lambda: service.observed_weather(start, end, resolution))


@app.get("/api/risk", response_model=RiskOut)
def risk() -> dict:
    return _call(service.risk)


@app.post("/api/simulate", response_model=SimulateOut)
def simulate(body: SimulateBody) -> dict:
    return _call(lambda: service.simulate(body.year))


@app.get("/api/backtest")
def backtest() -> dict:
    return _call(service.backtest)


@app.get("/api/demo/years")
def demo_years() -> dict:
    return _call(service.demo_years)


# Fixed anchor so a hypothetical preview does not depend on today's date.
# The installment amounts do not depend on the year. Due dates do.
_PREVIEW_FIRST_DUE = date(2000, 11, 1)


@app.get("/api/schedule/preview")
def schedule_preview(
    principal_cents: int = Query(..., gt=0),
    rate_bps: int = Query(..., ge=0, le=10000),
    term: int = Query(..., ge=1, le=600),
    kind: str = Query(...),
    value: int = Query(..., gt=0),
    start_month: int = Query(..., ge=1),
) -> dict:
    """Hypothetical before/after schedule. No chain call and no stored loan."""
    from chain.schedule import Relief, before_and_after

    def build() -> dict:
        relief_kind = kind.strip().upper()
        if relief_kind not in {"REDUCTION", "DEFERRAL"}:
            raise ValueError("kind must be REDUCTION or DEFERRAL")
        return before_and_after(
            principal_cents,
            rate_bps,
            term,
            _PREVIEW_FIRST_DUE,
            [Relief(relief_kind, value, start_month)],
        )

    return _call(build)


def _call(func):
    try:
        return func()
    except NotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SeasonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


from app.loans import router as loans_router

app.include_router(loans_router)

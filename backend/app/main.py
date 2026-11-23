"""RainCheck API, Phase 1.

The risk score is advice. Payment relief is a separate rainfall rule and is
not applied from this process yet (that is the contract phase).
"""

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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


@app.get("/api/risk")
def risk() -> dict:
    return _call(service.risk)


@app.post("/api/simulate")
def simulate(body: SimulateBody) -> dict:
    return _call(lambda: service.simulate(body.year))


def _call(func):
    try:
        return func()
    except NotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SeasonNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

"""Download daily weather from the Open-Meteo archive and cache it as CSV.

No API key. The cache is the demo's offline copy: if metadata matches the
region and the file is there, we do not call the network again.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

import httpx
import pandas as pd

from data.paths import CACHE_DIR, CACHE_META, DAILY_CSV

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = "precipitation_sum,temperature_2m_mean,temperature_2m_max,temperature_2m_min"


def default_end_date(today: date | None = None) -> date:
    # The archive lags the calendar by a few days. Asking for "today" often 400s.
    return (today or date.today()) - timedelta(days=5)


def load_or_fetch(region: dict, force: bool | None = None) -> pd.DataFrame:
    if force is None:
        force = os.environ.get("FORCE_REFRESH_WEATHER", "0") == "1"
    end = default_end_date()
    if not force and _cache_covers(region, end):
        return _read_cache()
    start = date.fromisoformat(region["history_start"])
    frame = None
    last_error: Exception | None = None
    # The archive sometimes rejects an end date that is still inside its lag.
    # Step back a month at a time instead of failing the whole demo.
    for _ in range(6):
        if (end - start).days < 20 * 365:
            break
        try:
            frame = fetch_daily(
                latitude=float(region["latitude"]),
                longitude=float(region["longitude"]),
                timezone=region["timezone"],
                start=start,
                end=end,
            )
            break
        except (httpx.HTTPError, RuntimeError) as exc:
            last_error = exc
            end = end - timedelta(days=30)
    if frame is None:
        raise RuntimeError(f"Open-Meteo archive request failed: {last_error}") from last_error
    _write_cache(frame, region, end)
    return frame


def fetch_daily(
    latitude: float,
    longitude: float,
    timezone: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """Fetch the whole span, then fall back to five-year chunks if the API refuses it."""
    try:
        return _fetch_range(latitude, longitude, timezone, start, end)
    except httpx.HTTPError:
        frames = []
        cursor = start
        while cursor <= end:
            chunk_end = min(date(cursor.year + 4, 12, 31), end)
            frames.append(_fetch_range(latitude, longitude, timezone, cursor, chunk_end))
            cursor = chunk_end + timedelta(days=1)
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
        return combined.reset_index(drop=True)


def _fetch_range(
    latitude: float,
    longitude: float,
    timezone: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": DAILY_VARS,
        "timezone": timezone,
    }
    headers = {"User-Agent": "RainCheck/0.1 (hackathon prototype; educational)"}
    with httpx.Client(timeout=120.0, headers=headers) as client:
        response = client.get(ARCHIVE_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    if not times:
        raise RuntimeError(f"Open-Meteo returned no daily rows for {start} to {end}: {payload}")
    frame = pd.DataFrame(
        {
            "date": times,
            "precipitation_mm": daily.get("precipitation_sum"),
            "temp_mean_c": daily.get("temperature_2m_mean"),
            "temp_max_c": daily.get("temperature_2m_max"),
            "temp_min_c": daily.get("temperature_2m_min"),
        }
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    return frame


def _cache_covers(region: dict, end: date) -> bool:
    if not DAILY_CSV.exists() or not CACHE_META.exists():
        return False
    meta = json.loads(CACHE_META.read_text(encoding="utf-8"))
    same_place = (
        meta.get("latitude") == float(region["latitude"])
        and meta.get("longitude") == float(region["longitude"])
        and meta.get("timezone") == region["timezone"]
        and meta.get("start_date") == region["history_start"]
    )
    if not same_place:
        return False
    cached_end = date.fromisoformat(meta["end_date"])
    return cached_end >= end - timedelta(days=2)


def _read_cache() -> pd.DataFrame:
    return pd.read_csv(DAILY_CSV, dtype={"date": str})


def _write_cache(frame: pd.DataFrame, region: dict, end: date) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    frame.to_csv(DAILY_CSV, index=False)
    meta = {
        "source": "Open-Meteo Archive API",
        "url": ARCHIVE_URL,
        "license_note": "Open-Meteo data is published under CC-BY 4.0. Attribute Open-Meteo.",
        "latitude": float(region["latitude"]),
        "longitude": float(region["longitude"]),
        "timezone": region["timezone"],
        "start_date": region["history_start"],
        "end_date": end.isoformat(),
        "rows": int(len(frame)),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    CACHE_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")

"""Download Nueva Ecija palay production and harvested area from PSA OpenSTAT.

From backend/:  .\\.venv\\Scripts\\python scripts\\fetch_harvest.py

Writes data/harvest/nueva_ecija_palay.json. The app reads that file only.
It never calls PSA while it runs. Yield is production divided by area.
Semester 2 is the July to December harvest, the crop that grows through
the June to October rain season.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "data" / "harvest" / "nueva_ecija_palay.json"
API = "https://openstat.psa.gov.ph/PXWeb/api/v1/en/DB/2E/CS/"
TABLES = {"production_t": "0012E4EVCP0.px", "area_ha": "0022E4EAHC0.px"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
PROVINCE = "....Nueva Ecija"
CROPS = {"Irrigated Palay": "irrigated", "Rainfed Palay": "rainfed", "Palay": "all"}
PERIODS = {"Semester 2": "wet_season", "Annual": "annual"}
FIRST_YEAR = 2001


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers=HEADERS)
    return json.loads(urllib.request.urlopen(request, timeout=60).read().decode("utf-8"))


def _post(url: str, body: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=HEADERS)
    return json.loads(urllib.request.urlopen(request, timeout=60).read().decode("utf-8-sig"))


def _codes(variable: dict, wanted) -> dict[str, str]:
    return {code: text for code, text in zip(variable["values"], variable["valueTexts"]) if text in wanted}


def _table(table: str) -> dict[tuple[str, str, str], float]:
    meta = _get(API + table)
    variables = {item["code"]: item for item in meta["variables"]}
    crops = _codes(variables["Ecosystem/Croptype"], CROPS)
    places = _codes(variables["Geolocation"], {PROVINCE})
    years = {
        code: text
        for code, text in zip(variables["Year"]["values"], variables["Year"]["valueTexts"])
        if int(text) >= FIRST_YEAR
    }
    periods = _codes(variables["Period"], PERIODS)
    if not crops or not places or not years or not periods:
        raise SystemExit(f"{table}: a variable code changed. Check the PSA table.")
    query = {
        "query": [
            {"code": "Ecosystem/Croptype", "selection": {"filter": "item", "values": list(crops)}},
            {"code": "Geolocation", "selection": {"filter": "item", "values": list(places)}},
            {"code": "Year", "selection": {"filter": "item", "values": list(years)}},
            {"code": "Period", "selection": {"filter": "item", "values": list(periods)}},
        ],
        "response": {"format": "json"},
    }
    body = _post(API + table, query)
    order = [column["code"] for column in body["columns"] if column.get("type") != "c"]
    found: dict[tuple[str, str, str], float] = {}
    for row in body["data"]:
        keys = dict(zip(order, row["key"]))
        raw = str(row["values"][0]).replace(",", "").strip()
        try:
            value = float(raw)
        except ValueError:
            continue
        crop = CROPS[crops[keys["Ecosystem/Croptype"]]]
        period = PERIODS[periods[keys["Period"]]]
        found[(years[keys["Year"]], crop, period)] = value
    return found


def main() -> int:
    production = _table(TABLES["production_t"])
    area = _table(TABLES["area_ha"])
    seasons: dict[str, dict] = {}
    for key in sorted(set(production) & set(area)):
        year, crop, period = key
        if area[key] <= 0:
            continue
        entry = seasons.setdefault(year, {}).setdefault(period, {})
        entry[crop] = {
            "production_t": production[key],
            "area_ha": area[key],
            "yield_t_per_ha": round(production[key] / area[key], 2),
        }
    payload = {
        "source": "Philippine Statistics Authority, OpenSTAT, Palay Production Survey",
        "tables": {name: API + table for name, table in TABLES.items()},
        "province": "Nueva Ecija",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wet_season_note": "Semester 2 is the July to December harvest. It is the crop grown through the June to October rain season.",
        "scope_note": "Province-wide. Most Nueva Ecija rice is irrigated. This is a comparison only. It does not change relief.",
        "seasons": seasons,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    wet = sum(1 for item in seasons.values() if "wet_season" in item)
    print(f"wrote {OUT.relative_to(BACKEND)}: {len(seasons)} years, {wet} with a wet-season harvest")
    return 0


if __name__ == "__main__":
    sys.exit(main())

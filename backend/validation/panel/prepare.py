"""Read the Mendeley workbook into district-year rows. Missing stays missing."""

from __future__ import annotations

import csv
from pathlib import Path

MONTHS = (
    "JUNE PERCIPITATION (Millimeters)",
    "JULY PERCIPITATION (Millimeters)",
    "AUGUST PERCIPITATION (Millimeters)",
    "SEPTEMBER PERCIPITATION (Millimeters)",
)

COLUMNS = (
    "district_id",
    "state",
    "name",
    "year",
    "yield_kg_ha",
    "season_mm",
    "dry2_mm",
    "irrig_share",
)

PANEL_SOURCE = (
    "Mohapatra, S. (2023). ICRISAT District-Level Data (Version 1). Mendeley Data. "
    "https://doi.org/10.17632/ywp3y5j9vv.1"
)
PANEL_ATTRIBUTION = (
    "Creative Commons Attribution 4.0. Credit Souryabrata Mohapatra and ICRISAT via Mendeley Data. "
    "June to September rain is the sum of the monthly columns. The stored rice yield is used. "
    "Blank cells and -1 were not filled. https://creativecommons.org/licenses/by/4.0/"
)


def _blank(value) -> bool:
    if value is None:
        return True
    try:
        if value != value:
            return True
    except Exception:
        return False
    return False


def _number(value) -> float | None:
    """A measurement. Blank and the ICRISAT missing code -1 are missing."""
    if _blank(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number == -1:
        return None
    return number


def _two_driest(months: list[float]) -> float:
    ordered = sorted(months)
    return ordered[0] + ordered[1]


def row_from_mapping(raw: dict) -> dict:
    months = [_number(raw.get(name)) for name in MONTHS]
    season = None if any(value is None or value < 0 for value in months) else sum(months)
    dry2 = None if season is None else _two_driest(months)
    cropped = _number(raw.get("GROSS CROPPED AREA (1000 ha)"))
    irrigated = _number(raw.get("GROSS IRRIGATED AREA (1000 ha)"))
    share = None
    if cropped is not None and cropped > 0 and irrigated is not None and irrigated >= 0:
        share = irrigated / cropped
    return {
        "district_id": None if _blank(raw.get("Dist Code")) else int(raw["Dist Code"]),
        "state": None if _blank(raw.get("State Name")) else str(raw["State Name"]),
        "name": None if _blank(raw.get("Dist Name")) else str(raw["Dist Name"]),
        "year": None if _blank(raw.get("Year")) else int(raw["Year"]),
        "yield_kg_ha": _number(raw.get("RICE YIELD (Kg per ha)")),
        "season_mm": season,
        "dry2_mm": dry2,
        "irrig_share": share,
    }


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = COLUMNS + ("source", "attribution")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            written = {key: "" if row.get(key) is None else row.get(key) for key in COLUMNS}
            written["source"] = PANEL_SOURCE
            written["attribution"] = PANEL_ATTRIBUTION
            writer.writerow(written)


def read_csv(path: Path) -> list[dict]:
    """Empty cells stay None. No gap is filled."""
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            item = {}
            for key in COLUMNS:
                text = (raw.get(key) or "").strip()
                if text == "":
                    item[key] = None
                elif key in ("district_id", "year"):
                    item[key] = int(float(text))
                elif key in ("state", "name"):
                    item[key] = text
                else:
                    item[key] = float(text)
            rows.append(item)
    return rows


def load_workbook(path: Path) -> list[dict]:
    import pandas as pd

    frame = pd.read_excel(path)
    return [row_from_mapping(record) for record in frame.to_dict(orient="records")]

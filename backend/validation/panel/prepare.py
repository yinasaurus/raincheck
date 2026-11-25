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
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row[key] is None else row[key] for key in COLUMNS})


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

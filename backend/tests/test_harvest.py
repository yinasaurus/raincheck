from pathlib import Path

from fastapi.testclient import TestClient

from app.harvest import harvest_rows, harvest_summary, load_harvest, trend_line
from app.main import app

BACKEND = Path(__file__).resolve().parents[1]


def _fake(yields: dict[int, float]) -> dict:
    return {"seasons": {str(year): {"wet_season": {"all": {"yield_t_per_ha": value}}} for year, value in yields.items()}}


def test_trend_line_recovers_a_straight_line():
    slope, intercept = trend_line({2001: 3.0, 2002: 3.5, 2003: 4.0, 2004: 4.5})
    assert abs(slope - 0.5) < 1e-9
    assert abs(slope * 2003 + intercept - 4.0) < 1e-9


def test_each_season_is_compared_to_the_trend_not_a_flat_average():
    rows = harvest_rows(_fake({2001: 3.0, 2002: 3.5, 2003: 4.4, 2004: 4.5}))
    assert rows[2003]["yield_t_per_ha"] == 4.4
    assert rows[2003]["vs_trend_pct"] > 0
    assert rows[2001]["vs_trend_pct"] is not None


def test_missing_file_leaves_no_harvest(tmp_path):
    assert load_harvest(tmp_path / "absent.json") is None
    assert harvest_rows(None) == {}
    assert harvest_summary(None) is None


def test_backtest_rows_carry_the_harvest_and_keep_the_rainfall_result():
    body = TestClient(app).get("/api/backtest").json()
    rows = {row["year"]: row for row in body["rows"]}
    assert len(rows) == 26
    assert body["payment_line_mm"] == 1363.0
    assert [year for year, row in rows.items() if row["relief_fired"]] == [2003, 2004, 2017]
    assert rows[2004]["harvest"]["yield_t_per_ha"] == 4.44
    assert rows[2004]["harvest"]["vs_trend_pct"] == 12
    assert rows[2017]["harvest"]["vs_trend_pct"] == 2
    assert rows[2026]["harvest"] is None
    summary = body["harvest"]
    assert summary["province"] == "Nueva Ecija"
    assert "Philippine Statistics Authority" in summary["source"]
    assert "does not change relief" in summary["scope_note"]


def test_the_payment_line_code_never_reads_the_harvest():
    files = [BACKEND / "data" / "trigger.py", BACKEND / "app" / "loans.py", *(BACKEND / "chain").rglob("*.py")]
    assert any(file.name == "oracle.py" for file in files)
    for file in files:
        assert "harvest" not in file.read_text(encoding="utf-8").lower(), file

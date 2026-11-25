from fastapi.testclient import TestClient

from app.main import app
from validation.analyze import HEADLINES, MIXED, SUPPORTS, WEAK, below_line_is_lower, verdict
from validation.report import build_validation


def _rows(pairs: list[tuple[int, float, bool]]) -> list[dict]:
    return [{"year": year, "season_total_mm": rain, "relief_fired": dry} for year, rain, dry in pairs]


def _harvest(pairs: list[tuple[int, float]]) -> dict:
    return {"fetched_at": "2026-11-24T00:00:00Z", "seasons": {str(year): {"wet_season": {"all": {"yield_t_per_ha": value}}} for year, value in pairs}}


def test_each_headline_wording_is_chosen_by_the_two_rules():
    assert verdict(True, True) == SUPPORTS
    assert verdict(True, False) == MIXED
    assert verdict(False, True) == MIXED
    assert verdict(False, False) == WEAK
    assert set(HEADLINES) == {SUPPORTS, MIXED, WEAK}
    assert "lined up with the dry seasons" in HEADLINES[SUPPORTS]
    assert "only partly lined up" in HEADLINES[MIXED]
    assert "did not line up" in HEADLINES[WEAK]


def test_a_lower_dry_year_median_is_the_supports_half_of_the_rule():
    assert below_line_is_lower([-20, -10], [0, 5, 8]) is True
    assert below_line_is_lower([12, 11, 2], [-6, 0, 8]) is False
    assert below_line_is_lower([], [1, 2]) is False


def _alternating(dry_when_low: bool) -> tuple[list[dict], dict]:
    rainfall = []
    yields = []
    for index, year in enumerate(range(2001, 2021)):
        low = index % 2 == 0
        rainfall.append((year, 1100 if low else 1900, low if dry_when_low else not low))
        yields.append((year, 4.0 + index * 0.02 + (-0.9 if low else 0.9)))
    return _rows(rainfall), _harvest(yields)


def test_the_saved_numbers_can_produce_each_wording():
    supports = build_validation(*_alternating(True))
    assert supports["validation"] == SUPPORTS
    assert supports["headline"] == HEADLINES[SUPPORTS]
    assert supports["spearman"]["excludes_zero"] is True
    assert supports["below_line_years"]["dry_years_below_other_median"] is True

    mixed = build_validation(*_alternating(False))
    assert mixed["validation"] == MIXED
    assert mixed["headline"] == HEADLINES[MIXED]

    weak = build_validation(
        _rows([(year, 1500 + year % 3 * 10, year >= 2010) for year in range(2001, 2016)]),
        _harvest([(year, 4.0 + (year - 2001) * 0.1) for year in range(2001, 2016)]),
    )
    assert weak["validation"] == WEAK
    assert weak["headline"] == HEADLINES[WEAK]


def test_a_year_with_no_harvest_is_null():
    missing = build_validation(
        _rows([(2001, 1500, False), (2026, 1700, False)]),
        _harvest([(2001, 4.0)]),
    )
    by_year = {row["year"]: row["yield_deviation_pct"] for row in missing["series"]}
    assert by_year[2026] is None
    assert missing["below_line_years"]["years"]["2003"] is None


def test_the_live_check_uses_the_saved_survey_and_leaves_2026_blank():
    body = TestClient(app).get("/api/validation").json()
    assert body["source_name"] == "PhilRice PalayStat"
    assert body["source_url"] == "https://palaystat.philrice.gov.ph/"
    assert body["retrieval_date"] == "2026-11-24"
    assert body["n"] == 25
    assert body["validation"] in HEADLINES
    assert body["headline"] == HEADLINES[body["validation"]]
    series = {row["year"]: row for row in body["series"]}
    assert series[2026]["yield_deviation_pct"] is None
    assert series[2026]["season_rainfall_mm"] is not None
    assert series[2004]["below_line"] is True
    assert series[2004]["yield_deviation_pct"] == 12
    assert series[2017]["yield_deviation_pct"] == 2
    assert len(body["worst_yield_years"]) == 5
    assert all(item["season_rainfall_mm"] is not None for item in body["worst_yield_years"])
    assert "typhoon" in " ".join(body["limitations"]).lower()
    assert "irrigat" in " ".join(body["limitations"]).lower()
    assert "July to December" in " ".join(body["limitations"])
    facts = TestClient(app).post(
        "/api/assistant",
        json={"question": "What does this chance mean?", "season": 2004, "week": 21},
    ).json()["facts_used"]
    labels = {item["label"]: item["value"] for item in facts}
    assert labels["Harvest check"] == body["headline"]
    assert labels["Harvest check result"] == body["validation"]
    assert "payment line" in labels["Harvest check limit 8"]

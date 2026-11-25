"""The district study keeps the yield line and the rainfall normal inside the training years."""

from pathlib import Path

from validation.panel.design import line_fit, spatial_fold, temporal_fold
from validation.panel.metrics import basis_risk_count, brier, false_alarm_rate, hit_rate, roc_auc, skill
from validation.panel.prepare import read_csv, row_from_mapping, write_csv


def _district(district, state, years, yield_of, rain_of, share=0.2):
    rows = []
    for year in years:
        rain = rain_of(year)
        rows.append({
            "district_id": district,
            "state": state,
            "name": f"D{district}",
            "year": year,
            "yield_kg_ha": yield_of(year),
            "season_mm": rain,
            "dry2_mm": rain / 2,
            "irrig_share": share,
        })
    return rows


def test_the_yield_line_uses_only_the_years_it_is_given():
    intercept, slope = line_fit([2000, 2001, 2002], [10, 12, 14])
    assert round(intercept, 6) == round(10 - 2 * 2000, 6)
    assert round(slope, 6) == 2


def test_a_later_year_does_not_enter_the_normal_or_the_line():
    early = list(range(2000, 2008))
    rows = _district(
        1,
        "Alpha",
        early + [2010],
        lambda year: 1.0 if year == 2010 else float(year),
        lambda year: 100.0 if year <= 2007 else 1000.0,
    )
    train, test = temporal_fold(rows)
    assert train and test
    assert max(row["year"] for row in train) <= 2007
    assert min(row["year"] for row in test) >= 2008
    assert test[0]["season_pct"] == 10
    assert test[0]["loss_10"] is True
    assert abs(test[0]["gap"] - ((1 / 2010 - 1) * 100)) < 1e-6


def test_a_held_out_state_is_absent_from_the_classifier_rows():
    years = list(range(2000, 2013))
    rows = []
    rows += _district(1, "Alpha", years, lambda year: float(year), lambda year: 80.0, 0.1)
    rows += _district(2, "Beta", years, lambda year: float(year), lambda year: 120.0, 0.9)
    train, test = spatial_fold(rows, "Alpha")
    assert train and test
    assert {row["state"] for row in train} == {"Beta"}
    assert {row["state"] for row in test} == {"Alpha"}
    assert all(row["year"] <= 2007 for row in train)
    assert all(row["year"] >= 2008 for row in test)
    train_ids = {row["district_id"] for row in train}
    test_ids = {row["district_id"] for row in test}
    assert train_ids.isdisjoint(test_ids)


def test_scores_on_a_toy_set_match_the_hand_count():
    labels = [1, 0, 1, 0]
    probs = [1.0, 0.0, 1.0, 0.0]
    fired = [True, False, True, False]
    assert brier(labels, probs) == 0
    assert skill(0, brier(labels, [0.5, 0.5, 0.5, 0.5])) == 1
    assert roc_auc(labels, probs) == 1
    assert hit_rate(labels, fired) == 1
    assert false_alarm_rate(labels, fired) == 0
    assert basis_risk_count(labels, fired) == 0
    assert roc_auc([1, 1], [0.2, 0.8]) is None


def test_a_blank_cell_stays_blank_and_minus_one_is_missing():
    mapped = row_from_mapping({
        "Dist Code": 7,
        "Year": 2004,
        "State Name": "Alpha",
        "Dist Name": "One",
        "RICE YIELD (Kg per ha)": None,
        "RICE AREA (1000 ha)": 10,
        "RICE PRODUCTION (1000 tons)": 20,
        "JUNE PERCIPITATION (Millimeters)": 10,
        "JULY PERCIPITATION (Millimeters)": 20,
        "AUGUST PERCIPITATION (Millimeters)": 30,
        "SEPTEMBER PERCIPITATION (Millimeters)": 40,
        "GROSS CROPPED AREA (1000 ha)": 50,
        "GROSS IRRIGATED AREA (1000 ha)": -1,
    })
    assert mapped["yield_kg_ha"] is None
    assert mapped["season_mm"] == 100
    assert mapped["dry2_mm"] == 30
    assert mapped["irrig_share"] is None
    folder = Path("data") / "panel" / "_test_rows.csv"
    write_csv([mapped], folder)
    try:
        restored = read_csv(folder)
    finally:
        folder.unlink()
    assert restored[0]["yield_kg_ha"] is None
    assert restored[0]["irrig_share"] is None
    assert restored[0]["district_id"] == 7

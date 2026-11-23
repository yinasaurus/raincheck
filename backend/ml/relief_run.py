"""Compare relief-probability candidates and write the leave-one-out file.

Run from backend/:

    python -m ml.relief_run

This does not replace the v1 model, metrics, or loo_scores.json.
The winner is chosen by ml.relief.choose_method, which sees only mean Brier scores.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

from data.aggregate import prepare_daily, season_bounds
from data.open_meteo import load_or_fetch
from data.paths import LOO_SCORES_PATH, MODEL_DIR, REGION_PATH, RELIEF_PATH
from ml.features import FEATURE_COLUMNS, buckets_for_years, build_feature_frame
from ml.labels import label_seasons
from ml.relief import (
    CHECKPOINTS,
    DISTRIBUTION_METHODS,
    N_POSITIVE_SEASONS_NOTE,
    N_SCORED_WEEKS,
    PAYMENT_LINE_MM,
    PAYMENT_LINE_TENTHS,
    SeasonCurve,
    analog_raw,
    analog_scaled,
    brier_skill,
    bootstrap_mean_brier,
    build_curve,
    climatology_probability,
    calibration_table,
    choose_method,
    earliest_week,
    fraction_of_normal,
    gamma_remaining,
    log_loss,
    logistic_probability,
    lognormal_remaining,
    longest_dry_spell,
    metric_row,
    normal_to_date,
    relief_fired,
    roc_auc,
    rule_score,
    tenths_to_mm,
    wet_days_first_four_weeks,
)
from ml.train import MODEL_PARAMS, _balanced_weights

NO_TEMP_COLUMNS = [
    name for name in FEATURE_COLUMNS if name not in {"temp_mean_to_date", "temp_max_to_date", "hot_days_to_date"}
]


def main() -> None:
    region = json.loads(REGION_PATH.read_text(encoding="utf-8"))
    daily = prepare_daily(load_or_fetch(region))
    months = [int(month) for month in region["planting_season_months"]]
    curves = _curves(daily, months)
    if len(curves) != 26:
        raise SystemExit(f"Expected 26 complete seasons, found {len(curves)}.")
    labels = {curve.year: relief_fired(curve.season_tenths) for curve in curves}
    positives = sorted(year for year, fired in labels.items() if fired)
    print(f"Seasons below 1363.0 mm: {positives} ({len(positives)} of {len(curves)})")

    v1 = _v1_probabilities()
    v1_no_temp = _v1_without_temperature(region, daily, months)
    grid = _score_all(curves, labels, v1, v1_no_temp)
    candidates, mean_brier, per_season_brier = _summarize(grid, labels)
    # Climatology is the no-skill reference for the skill score. It is not one of the 8 candidates.
    selectable = {name: score for name, score in mean_brier.items() if name != "climatology"}
    method = choose_method(selectable)
    print("Mean Brier with week 21 (selection) and without week 21 (headline):")
    for name in sorted(selectable, key=selectable.get):
        mark = "  <-- chosen" if name == method else ""
        without = candidates[name]["mean_brier_without_week_21"]
        print(f"  {name:16} with {mean_brier[name]:.4f}  without {without:.4f}{mark}")
    climate = candidates["climatology"]
    print(
        f"  {'climatology':16} with {climate['mean_brier_with_week_21']:.4f}"
        f"  without {climate['mean_brier_without_week_21']:.4f}  (not a candidate)"
    )
    if mean_brier[method] >= mean_brier["rule"] - 1e-12 and method != "rule":
        print("Chosen method is within a tie of the rule and won on simplicity.")
    if method == "rule" or mean_brier[method] > mean_brier["rule"] - 1e-12 and method != "rule":
        pass
    beats_rule = mean_brier[method] < mean_brier["rule"] - 1e-12
    print(f"Beats the rule baseline: {beats_rule}")

    projection_method = method if method in DISTRIBUTION_METHODS else "analog_raw"
    scores = _export_scores(grid, method, projection_method)
    lead = _lead_table(grid, labels, method)
    calibration = _calibration(grid, labels, method)
    trend = _trend(curves)
    spells = _dry_spells(curves, labels)
    newer = _newer_years(curves, labels, grid, method)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "made_after_audit": True,
        "target": "P(season total ends strictly below 1363.0 mm | rainfall through week w)",
        "payment_line_mm": PAYMENT_LINE_MM,
        "payment_line_tenths": PAYMENT_LINE_TENTHS,
        "n_seasons": len(curves),
        "n_positive_seasons": len(positives),
        "positive_seasons": positives,
        "small_sample_note": N_POSITIVE_SEASONS_NOTE,
        "selection_rule": (
            "Lowest mean Brier score across weeks 4, 8, 12, 16 and 21. "
            "A gap of 0.005 or less is a tie, broken by simplicity: "
            "rule, logistic, analog_raw, analog_scaled, lognormal, gamma, v1_no_temp, v1. "
            "Per-year plots were not used. Climatology is not a candidate."
        ),
        "selection_bias": (
            "The winner was chosen from 8 candidates on the same 26 seasons, 3 of them positive. "
            "That score is optimistically biased."
        ),
        "headline_metric": "mean_brier_without_week_21",
        "method": method,
        "projection_method": projection_method,
        "beats_rule_baseline": beats_rule,
        "candidates": candidates,
        "mean_brier": mean_brier,
        "bootstrap": {
            "chosen": bootstrap_mean_brier(per_season_brier[method]),
            "rule": bootstrap_mean_brier(per_season_brier["rule"]),
        },
        "lead_time": lead,
        "calibration": calibration,
        "trend": trend,
        "dry_spells": spells,
        "newer_years": newer,
        "scores": scores,
    }
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RELIEF_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {RELIEF_PATH}")
    _print_tables(lead, newer, trend, spells, candidates, method)


def _curves(daily: pd.DataFrame, months: list[int]) -> list[SeasonCurve]:
    curves = []
    for year in sorted(int(value) for value in daily["date"].dt.year.unique()):
        start, end = season_bounds(year, months)
        window = daily[(daily["date"] >= pd.Timestamp(start)) & (daily["date"] <= pd.Timestamp(end))]
        if len(window) < N_SCORED_WEEKS * 7:
            continue
        expected = (end - start).days + 1
        if len(window) != expected:
            continue
        values = []
        for value in window["precipitation_mm"].tolist():
            values.append(0.0 if pd.isna(value) else float(value))
        curves.append(build_curve(year, values))
    return curves


def _v1_probabilities() -> dict[int, dict[int, float]]:
    payload = json.loads(LOO_SCORES_PATH.read_text(encoding="utf-8"))
    scores = {}
    for year, weeks in payload["scores"].items():
        scores[int(year)] = {int(week): float(row["model_probability"]) for week, row in weeks.items()}
    return scores


def _v1_without_temperature(region: dict, daily: pd.DataFrame, months: list[int]) -> dict[int, dict[int, float]]:
    """Same v1 classifier, SPI label, temperature features removed. Not the served model."""
    labeled = label_seasons(season_totals_frame(daily, months), spi_threshold=float(region["drought_label"]["threshold"]))
    complete = labeled[labeled["drought_stress"].notna()]
    labels = {int(row.year): bool(row.drought_stress) for row in complete.itertuples()}
    years = sorted(labels)
    buckets = buckets_for_years(daily, years, months, float(region["heat_day_celsius"]))
    stored: dict[int, dict[int, float]] = {}
    for held in years:
        train_years = [year for year in years if year != held]
        train = build_feature_frame(buckets, train_years, train_years, labels, N_SCORED_WEEKS)
        test = build_feature_frame(buckets, [held], train_years, labels, N_SCORED_WEEKS)
        target = train["drought_stress"].astype(int).to_numpy()
        model = GradientBoostingClassifier(**MODEL_PARAMS)
        model.fit(train[NO_TEMP_COLUMNS], target, sample_weight=_balanced_weights(target))
        stored[held] = {}
        for _, row in test.iterrows():
            frame = pd.DataFrame([row[NO_TEMP_COLUMNS].astype(float)], columns=NO_TEMP_COLUMNS)
            stored[held][int(row["week_index"])] = float(model.predict_proba(frame)[0, 1])
    return stored


def season_totals_frame(daily: pd.DataFrame, months: list[int]) -> pd.DataFrame:
    from data.aggregate import season_totals

    return season_totals(daily, months)


def _score_all(curves, labels, v1, v1_no_temp) -> dict:
    """grid[method][year][week] = {p_relief, projected_total_mm or None, rule_score, rain_pct}."""
    methods = {name: {} for name in (
        "v1", "v1_no_temp", "rule", "logistic", "analog_raw", "analog_scaled", "gamma", "lognormal", "climatology"
    )}
    by_year = {curve.year: curve for curve in curves}
    for held in by_year:
        others = [curve for curve in curves if curve.year != held]
        other_positives = sum(1 for year, fired in labels.items() if year != held and fired)
        climate = climatology_probability(other_positives, len(curves) - 1)
        methods["v1"][held] = {}
        methods["v1_no_temp"][held] = {}
        for name in ("rule", "logistic", "analog_raw", "analog_scaled", "gamma", "lognormal", "climatology"):
            methods[name][held] = {}
        for week in range(1, N_SCORED_WEEKS + 1):
            to_date = by_year[held].to_date_tenths(week)
            normal = normal_to_date(curves, week, exclude_year=held)
            fraction = fraction_of_normal(to_date, normal)
            remainders = [curve.remainder_tenths(week) for curve in others]
            peers = [(curve.to_date_tenths(week), curve.remainder_tenths(week)) for curve in others]
            raw = analog_raw(to_date, remainders)
            scaled = analog_scaled(to_date, peers)
            gamma = gamma_remaining(to_date, remainders)
            lognormal = lognormal_remaining(to_date, remainders)
            rule = rule_score(fraction)
            # Each training season's normal leaves out that season and the held-out season.
            train_fractions = []
            train_labels = []
            for curve in others:
                both_out = [other.to_date_tenths(week) for other in curves if other.year not in {curve.year, held}]
                peer_normal = float(np.mean(both_out))
                train_fractions.append(fraction_of_normal(curve.to_date_tenths(week), peer_normal))
                train_labels.append(int(labels[curve.year]))
            logistic = logistic_probability(train_fractions, train_labels, fraction)
            common = {
                "rule_score": rule,
                "rain_pct_of_normal": fraction,
                "to_date_mm": tenths_to_mm(to_date),
            }
            pack = {
                "v1": {**common, "p_relief": v1[held][week], "projected_total_mm": None},
                "v1_no_temp": {**common, "p_relief": v1_no_temp[held][week], "projected_total_mm": None},
                "rule": {**common, "p_relief": rule, "projected_total_mm": None},
                "analog_raw": {**common, "p_relief": raw["p_relief"], "projected_total_mm": raw["projected_total_mm"]},
                "analog_scaled": {**common, "p_relief": scaled["p_relief"], "projected_total_mm": scaled["projected_total_mm"]},
                "gamma": {**common, "p_relief": gamma["p_relief"], "projected_total_mm": gamma["projected_total_mm"]},
                "lognormal": {**common, "p_relief": lognormal["p_relief"], "projected_total_mm": lognormal["projected_total_mm"]},
            }
            pack["logistic"] = {**common, "p_relief": logistic, "projected_total_mm": None}
            pack["climatology"] = {**common, "p_relief": climate, "projected_total_mm": None, "rule_score": None}
            for name, row in pack.items():
                methods[name][held][week] = row
    return methods


def _summarize(grid, labels) -> tuple[dict, dict, dict]:
    candidates = {}
    mean_brier = {}
    per_season = {}
    for name, by_year in grid.items():
        by_week = {}
        season_briers = []
        for year, fired in labels.items():
            squares = []
            for week in CHECKPOINTS:
                row = by_year[year].get(week)
                if row is None:
                    continue
                squares.append((row["p_relief"] - float(fired)) ** 2)
            if squares:
                season_briers.append(float(np.mean(squares)))
        for week in CHECKPOINTS:
            probability = []
            actual = []
            for year, fired in labels.items():
                row = by_year[year].get(week)
                if row is None:
                    continue
                probability.append(row["p_relief"])
                actual.append(int(fired))
            by_week[str(week)] = metric_row(probability, actual)
        mean_brier[name] = float(np.mean([row["brier"] for row in by_week.values()]))
        without_21 = [by_week[str(week)]["brier"] for week in CHECKPOINTS if week != 21]
        per_season[name] = season_briers
        first = _lead_for_method(by_year, labels)
        candidates[name] = {
            "mean_brier": mean_brier[name],
            "mean_brier_with_week_21": mean_brier[name],
            "mean_brier_without_week_21": float(np.mean(without_21)),
            "by_week": by_week,
            "lead_time": first,
            "false_alarms": sum(1 for row in first if row["false_alarm"]),
        }
    climate_weeks = candidates["climatology"]["by_week"]
    for cand in candidates.values():
        for week, row in cand["by_week"].items():
            row["brier_skill"] = brier_skill(row["brier"], climate_weeks[week]["brier"])
    return candidates, mean_brier, per_season


def _lead_for_method(by_year, labels) -> list[dict]:
    rows = []
    for year, fired in sorted(labels.items()):
        weeks = {week: row["p_relief"] for week, row in by_year[year].items()}
        first = earliest_week(weeks)
        alarm = (not fired) and first is not None
        rows.append(
            {
                "year": year,
                "relief_fired": bool(fired),
                "first_week_p_relief_at_least_0_5": first,
                "false_alarm": alarm,
                "max_p_relief": max(weeks.values()) if weeks else None,
            }
        )
    return rows


def _export_scores(grid, method: str, projection_method: str) -> dict:
    exported = {}
    for year, weeks in grid[method].items():
        exported[str(year)] = {}
        for week, row in weeks.items():
            projected = row["projected_total_mm"]
            if projected is None:
                projected = grid[projection_method][year][week]["projected_total_mm"]
            exported[str(year)][str(week)] = {
                "p_relief": round(float(row["p_relief"]), 4),
                "rule_score": round(float(row["rule_score"]), 4),
                "rain_pct_of_normal": round(float(row["rain_pct_of_normal"]), 4),
                "to_date_mm": row["to_date_mm"],
                "projected_total_mm": projected,
                "method": method,
                "projection_method": projection_method,
            }
    return exported


def _lead_table(grid, labels, method: str) -> dict:
    focus = []
    alarms = 0
    for row in _lead_for_method(grid[method], labels):
        if row["relief_fired"]:
            focus.append(row)
        elif row["false_alarm"]:
            alarms += 1
    return {
        "relief_years": focus,
        "false_alarms_among_the_other_23": alarms,
        "note": "Earliest week is any week 1-21, not only the five checkpoints. A false alarm is a season that finished on or above the line and still reached p_relief >= 0.5.",
    }


def _calibration(grid, labels, method: str) -> list[dict]:
    probability = []
    actual = []
    for year, fired in labels.items():
        for week in CHECKPOINTS:
            probability.append(grid[method][year][week]["p_relief"])
            actual.append(int(fired))
    return calibration_table(probability, actual)


def _trend(curves: list[SeasonCurve]) -> dict:
    from scipy.stats import linregress

    years = np.array([curve.year for curve in curves], dtype=float)
    totals = np.array([tenths_to_mm(curve.season_tenths) for curve in curves], dtype=float)
    slope, intercept, _r, p_value, _se = linregress(years, totals)
    rolling = []
    for end in range(curves[0].year + 9, curves[-1].year + 1):
        window = [curve for curve in curves if end - 9 <= curve.year <= end]
        if len(window) == 10:
            rolling.append(
                {
                    "end_year": end,
                    "mean_mm": round(float(np.mean([tenths_to_mm(curve.season_tenths) for curve in window])), 1),
                }
            )
    windows = [(2001, 2010), (2011, 2020), (2021, 2026)]
    counts = []
    for start, end in windows:
        chosen = [curve for curve in curves if start <= curve.year <= end]
        below = sum(1 for curve in chosen if relief_fired(curve.season_tenths))
        counts.append(
            {
                "window": f"{start}-{end}",
                "seasons": len(chosen),
                "below_the_line": below,
                "note": f"{len(chosen)} seasons. Too few to call a change in drought frequency.",
            }
        )
    return {
        "season_totals_mm": [
            {"year": curve.year, "season_total_mm": tenths_to_mm(curve.season_tenths)} for curve in curves
        ],
        "linear_trend_mm_per_year": round(float(slope), 2),
        "linear_trend_p_value": float(p_value),
        "trend_note": (
            "Ordinary least squares on 26 season totals. The p-value is reported and is not a claim "
            "that the trend is real. One or two seasons move the slope."
        ),
        "rolling_10_year_mean_mm": rolling,
        "below_the_line_by_window": counts,
        "intercept_mm": round(float(intercept), 1),
    }


def _dry_spells(curves: list[SeasonCurve], labels: dict[int, bool]) -> dict:
    rows = []
    for curve in curves:
        rows.append(
            {
                "year": curve.year,
                "longest_dry_spell_days": longest_dry_spell(list(curve.daily_mm)),
                "days_above_1mm_in_first_4_weeks": wet_days_first_four_weeks(list(curve.daily_mm)),
                "relief_fired": bool(labels[curve.year]),
            }
        )
    relief_spells = [row["longest_dry_spell_days"] for row in rows if row["relief_fired"]]
    median_spell = int(np.median(relief_spells)) if relief_spells else None
    flagged = [
        row["year"]
        for row in rows
        if row["year"] >= 2018 and not row["relief_fired"] and median_spell is not None and row["longest_dry_spell_days"] >= median_spell
    ]
    return {
        "definition": (
            "A dry day is strictly below 1 mm. A long spell is at least as long as the median "
            "longest spell of the seasons that finished below the payment line. "
            "This does not change the trigger. A season-total trigger can miss a damaging dry spell."
        ),
        "median_spell_of_relief_years": median_spell,
        "seasons_since_2017_above_the_line_with_a_long_spell": flagged,
        "by_year": rows,
    }


def _newer_years(curves, labels, grid, method: str) -> list[dict]:
    normal = float(np.mean([curve.season_tenths for curve in curves]))
    rows = []
    for curve in curves:
        if curve.year < 2018:
            continue
        weeks = {week: row["p_relief"] for week, row in grid[method][curve.year].items()}
        rows.append(
            {
                "year": curve.year,
                "season_total_mm": tenths_to_mm(curve.season_tenths),
                "pct_of_26_year_normal": round(curve.season_tenths / normal, 3),
                "relief_fired": bool(labels[curve.year]),
                "max_p_relief": round(max(weeks.values()), 4),
                "first_week_p_relief_at_least_0_5": earliest_week(weeks),
            }
        )
    return rows


def _print_tables(lead, newer, trend, spells, candidates, method) -> None:
    print("\nLead time")
    for row in lead["relief_years"]:
        print(f"  {row['year']}: first week >= 0.5 -> {row['first_week_p_relief_at_least_0_5']} max {row['max_p_relief']:.3f}")
    print(f"  false alarms: {lead['false_alarms_among_the_other_23']}")
    print("\n2018-2026")
    for row in newer:
        print(
            f"  {row['year']}: {row['season_total_mm']} mm  {row['pct_of_26_year_normal']:.0%} of normal  "
            f"relief {row['relief_fired']}  max p {row['max_p_relief']:.3f}  first {row['first_week_p_relief_at_least_0_5']}"
        )
    print("\nTrend slope", trend["linear_trend_mm_per_year"], "p", round(trend["linear_trend_p_value"], 3))
    print("Windows", trend["below_the_line_by_window"])
    print("Long spells since 2017 while above the line:", spells["seasons_since_2017_above_the_line_with_a_long_spell"])
    print("\nCheckpoint Brier / log loss / AUC for", method)
    for week, row in candidates[method]["by_week"].items():
        print(f"  week {week}: brier {row['brier']:.3f}  logloss {row['log_loss']:.3f}  auc {row['roc_auc']}")


if __name__ == "__main__":
    main()

"""Train the drought-stress model and write an honest held-out report.

Run from the backend directory:

    python -m ml.train

Hyperparameters are fixed for a small sample (shallow trees, no search).
Do not retune them after seeing the score and then quote the improved number.
The headline metrics are leave-one-season-out at week 12. Week 21 is reported
only as a late-season check: by then the feature rainfall is almost the same
rainfall the label is built from, so a high score is not an early warning.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, recall_score, roc_auc_score

from data.aggregate import calendar_season_weeks, season_totals
from data.open_meteo import load_or_fetch
from data.paths import LOO_SCORES_PATH, METRICS_PATH, MODEL_DIR, MODEL_PATH, REGION_PATH
from data.trigger import agreed_trigger_mm
from ml.baseline import baseline_calls_drought, baseline_probability
from ml.explain import positive_probability, top_factors
from ml.features import FEATURE_COLUMNS, buckets_for_years, build_feature_frame
from ml.labels import label_seasons

# Chosen before looking at scores. Shallow on purpose: we have ~25 seasons.
MODEL_PARAMS = {
    "n_estimators": 100,
    "max_depth": 2,
    "learning_rate": 0.05,
    "min_samples_leaf": 8,
    "subsample": 0.9,
    "random_state": 42,
}
# Mid-season is the number we quote. Week 21 is almost the full window.
HEADLINE_WEEK = 12
EXTRA_WEEKS = (8, 21)
MIN_SEASONS = 15


def main() -> None:
    region = json.loads(REGION_PATH.read_text(encoding="utf-8"))
    print("Loading weather (cache hit, or a download from Open-Meteo)...")
    daily = load_or_fetch(region)
    labeled, frame, buckets, season_weeks = prepare(region, daily)
    years = sorted(int(year) for year in frame["year"].unique())
    drought_years = sorted(int(year) for year in frame.loc[frame["drought_stress"], "year"].unique())
    print(f"Complete seasons with features: {len(years)} ({years[0]}-{years[-1]})")
    print(f"Proxy drought seasons (SPI <= {region['drought_label']['threshold']}): {drought_years or 'none'}")

    metrics, loo_scores = evaluate_leave_one_season_out(buckets, years, _labels(labeled), season_weeks)
    model = fit_model(frame)
    medians = frame[FEATURE_COLUMNS].median(numeric_only=True)
    importances = {
        name: float(value)
        for name, value in zip(FEATURE_COLUMNS, model.feature_importances_)
    }
    trigger = _trigger_mm(region, labeled)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "feature_columns": FEATURE_COLUMNS,
        "medians": medians,
        "global_importance": importances,
        "trained_on_years": years,
        "model_params": MODEL_PARAMS,
        "season_weeks": season_weeks,
    }
    import joblib

    joblib.dump(bundle, MODEL_PATH)
    report = _report(region, labeled, metrics, importances, trigger, season_weeks, drought_years)
    METRICS_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LOO_SCORES_PATH.write_text(
        json.dumps(
            {
                "protocol": "leave-one-season-out probability for every full season week",
                "note": (
                    "Historical replays use these scores. The served model is trained on every "
                    "season, so its score for a past year has already seen that year."
                ),
                "scores": loo_scores,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _print_report(report)
    print(f"Wrote {MODEL_PATH}")
    print(f"Wrote {METRICS_PATH}")
    print(f"Wrote {LOO_SCORES_PATH}")


def prepare(region: dict, daily: pd.DataFrame):
    months = [int(month) for month in region["planting_season_months"]]
    threshold = float(region["drought_label"]["threshold"])
    heat = float(region["heat_day_celsius"])
    season_weeks = calendar_season_weeks(months)
    labeled = label_seasons(season_totals(daily, months), spi_threshold=threshold)
    complete = labeled[labeled["drought_stress"].notna()].copy()
    if len(complete) < MIN_SEASONS:
        raise SystemExit(
            f"Only {len(complete)} complete seasons. Need at least {MIN_SEASONS} "
            "before training. Check the cache and the season months."
        )
    labels = {int(row.year): bool(row.drought_stress) for row in complete.itertuples()}
    if len(set(labels.values())) < 2:
        raise SystemExit(
            "Every complete season has the same proxy label, so there is nothing "
            "to train. The threshold or the rainfall record needs a closer look. "
            "No model file was written."
        )
    years = sorted(labels)
    buckets = buckets_for_years(daily, years, months, heat)
    frame = build_feature_frame(buckets, years, years, labels, season_weeks)
    if frame.empty:
        raise SystemExit("Feature table is empty. The weekly buckets may all be partial.")
    return labeled, frame, buckets, season_weeks


def evaluate_leave_one_season_out(buckets, years, labels, season_weeks) -> tuple[dict, dict]:
    """Each season is scored by a model that did not train on that season.

    Checkpoint rows feed the published metrics. Every full week is also stored
    so a historical replay can show that held-out score instead of the
    served model, which has already seen the season.
    """
    stored: dict[int, list[dict]] = {week: [] for week in (HEADLINE_WEEK, *EXTRA_WEEKS)}
    loo_scores: dict[str, dict] = {}
    for held in years:
        train_years = [year for year in years if year != held]
        train_frame = build_feature_frame(buckets, train_years, train_years, labels, season_weeks)
        test_frame = build_feature_frame(buckets, [held], train_years, labels, season_weeks)
        if train_frame.empty or test_frame.empty or train_frame["drought_stress"].nunique() < 2:
            continue
        model = fit_model(train_frame)
        medians = train_frame[FEATURE_COLUMNS].median(numeric_only=True)
        year_scores: dict[str, dict] = {}
        for _, row in test_frame.iterrows():
            features = pd.DataFrame([row[FEATURE_COLUMNS].astype(float)], columns=FEATURE_COLUMNS)
            probability = float(positive_probability(model, features)[0])
            pct = float(row["cumulative_pct_of_normal"])
            factors = top_factors(model, row, medians, FEATURE_COLUMNS, limit=3)
            week = int(row["week_index"])
            year_scores[str(week)] = {
                "model_probability": probability,
                "baseline_probability": float(baseline_probability([pct])[0]),
                "cumulative_pct_of_normal": pct,
                "top_factors": factors,
            }
            if week in stored:
                stored[week].append(
                    {
                        "year": int(held),
                        "drought_stress": bool(labels[held]),
                        "model_probability": probability,
                        "model_calls_drought": probability >= 0.5,
                        "baseline_probability": float(baseline_probability([pct])[0]),
                        "baseline_calls_drought": bool(baseline_calls_drought([pct])[0]),
                        "cumulative_pct_of_normal": pct,
                    }
                )
        loo_scores[str(int(held))] = year_scores
    return {str(week): _summarize(rows) for week, rows in stored.items()}, loo_scores


def fit_model(frame: pd.DataFrame) -> GradientBoostingClassifier:
    target = frame["drought_stress"].astype(int).to_numpy()
    if len(np.unique(target)) < 2:
        raise RuntimeError("training fold has only one class")
    model = GradientBoostingClassifier(**MODEL_PARAMS)
    model.fit(frame[FEATURE_COLUMNS], target, sample_weight=_balanced_weights(target))
    return model


def _balanced_weights(target: np.ndarray) -> np.ndarray:
    positives = max(int((target == 1).sum()), 1)
    negatives = max(int((target == 0).sum()), 1)
    total = len(target)
    return np.where(target == 1, 0.5 * total / positives, 0.5 * total / negatives).astype(float)


def _summarize(rows: list[dict]) -> dict:
    if not rows:
        return {"n_seasons": 0, "note": "No season had this week index."}
    actual = np.array([row["drought_stress"] for row in rows], dtype=int)
    model_probability = np.array([row["model_probability"] for row in rows])
    model_pred = np.array([row["model_calls_drought"] for row in rows], dtype=int)
    base_probability = np.array([row["baseline_probability"] for row in rows])
    base_pred = np.array([row["baseline_calls_drought"] for row in rows], dtype=int)
    return {
        "n_seasons": int(len(rows)),
        "n_drought": int(actual.sum()),
        "model": _scores(actual, model_probability, model_pred),
        "baseline": _scores(actual, base_probability, base_pred),
        "false_negatives": [
            int(row["year"]) for row in rows if row["drought_stress"] and not row["model_calls_drought"]
        ],
        "false_positives": [
            int(row["year"]) for row in rows if not row["drought_stress"] and row["model_calls_drought"]
        ],
        "by_year": rows,
    }


def _scores(actual: np.ndarray, probability: np.ndarray, predicted: np.ndarray) -> dict:
    scores = {
        "accuracy": float(accuracy_score(actual, predicted)),
        "recall_drought": None,
        "roc_auc": None,
    }
    if int(actual.sum()) > 0:
        scores["recall_drought"] = float(recall_score(actual, predicted, pos_label=1, zero_division=0))
    if len(set(actual.tolist())) > 1:
        scores["roc_auc"] = float(roc_auc_score(actual, probability))
    return scores


def _labels(labeled: pd.DataFrame) -> dict[int, bool]:
    complete = labeled[labeled["drought_stress"].notna()]
    return {int(row.year): bool(row.drought_stress) for row in complete.itertuples()}


def _trigger_mm(region: dict, labeled: pd.DataFrame) -> int:
    complete = labeled[labeled["drought_stress"].notna()]
    average = float(complete["rainfall_mm"].mean())
    override = region["trigger"].get("rainfall_mm")
    return agreed_trigger_mm(
        average,
        float(region["trigger"]["pct_of_long_term_average"]),
        override_mm=None if override is None else float(override),
    )


def _report(region, labeled, metrics, importances, trigger, season_weeks, drought_years) -> dict:
    complete = labeled[labeled["drought_stress"].notna()].copy()
    headline = metrics.get(str(HEADLINE_WEEK), {})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weather_source": "Open-Meteo Archive API, cached on disk. CC-BY 4.0, attribute Open-Meteo.",
        "region": {
            "name": region["name"],
            "country": region["country"],
            "latitude": region["latitude"],
            "longitude": region["longitude"],
            "crop": region["crop"],
            "planting_season_months": region["planting_season_months"],
        },
        "label": {
            "name": "seasonal_spi_gamma",
            "threshold": region["drought_label"]["threshold"],
            "definition": region["drought_label"]["definition"],
            "proxy": True,
            "not_a_yield_label": True,
        },
        "n_complete_seasons": int(len(complete)),
        "season_year_start": int(complete["year"].min()),
        "season_year_end": int(complete["year"].max()),
        "n_proxy_drought_seasons": len(drought_years),
        "proxy_drought_years": drought_years,
        "long_term_average_season_rainfall_mm": float(complete["rainfall_mm"].mean()),
        "proposed_trigger_rainfall_mm": trigger,
        "trigger_rule": (
            "Integer millimetres, half-up rounding, fire only when observed season "
            "rainfall is strictly below the trigger. The model score is not an input. "
            "Default trigger is 80% of the long-term average seasonal rainfall."
        ),
        "model": {
            "type": "gradient_boosting",
            "params": MODEL_PARAMS,
            "decision_threshold": 0.5,
            "class_weight": "balanced sample weights",
            "global_importance": importances,
            "served_model_trained_on": "all complete seasons, after the leave-one-season-out scores were computed",
        },
        "evaluation": {
            "protocol": "leave-one-season-out. Each test row is one season, scored at a single week.",
            "headline_week": HEADLINE_WEEK,
            "season_weeks": season_weeks,
            "by_week": metrics,
            "small_sample_note": (
                f"The independent sample is about {len(complete)} seasons, and only "
                f"{len(drought_years)} of them are proxy-drought seasons. Accuracy, recall, "
                "and ROC-AUC will move a lot if one year is added or removed. Do not read "
                "week-rows as extra samples: weeks inside one season share one label. "
                "Week 21 uses nearly the whole season's rain, which is also what the label "
                "is built from, so it is not an early-warning result. No threshold or "
                "hyperparameter was adjusted after seeing these numbers."
            ),
        },
    }


def _print_report(report: dict) -> None:
    headline = report["evaluation"]["by_week"].get(str(HEADLINE_WEEK), {})
    print()
    print(f"Leave-one-season-out at week {HEADLINE_WEEK} (one row per season)")
    print(f"  seasons scored: {headline.get('n_seasons')}  proxy droughts in that set: {headline.get('n_drought')}")
    for name in ("model", "baseline"):
        scores = headline.get(name) or {}
        print(
            f"  {name}: accuracy={_fmt(scores.get('accuracy'))} "
            f"recall_drought={_fmt(scores.get('recall_drought'))} "
            f"roc_auc={_fmt(scores.get('roc_auc'))}"
        )
    print(f"Proposed trigger: {report['proposed_trigger_rainfall_mm']} mm")
    print(report["evaluation"]["small_sample_note"])


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


if __name__ == "__main__":
    main()

"""Fit the locked models once. Parameters are not chosen from the test scores."""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

from validation.panel.design import THRESHOLDS, spatial_fold, temporal_fold, tertile, tertile_cuts
from validation.panel.metrics import (
    basis_risk_count,
    brier,
    calibration,
    false_alarm_rate,
    hit_rate,
    roc_auc,
    skill,
)
from validation.panel.prepare import load_workbook, read_csv, write_csv

DRAWS = 1000
SEED = 1363
FEATURES = ("season_pct", "dry_pct", "irrig_share", "interact")


def _percent(samples: list[float], percent: float) -> float:
    if len(samples) == 1:
        return samples[0]
    pos = (len(samples) - 1) * percent / 100.0
    low = int(pos)
    high = min(low + 1, len(samples) - 1)
    return samples[low] * (1 - (pos - low)) + samples[high] * (pos - low)


def _interval(rows: list[dict], value_fn) -> dict:
    by_district: dict[object, list[int]] = {}
    for index, row in enumerate(rows):
        by_district.setdefault(row["district_id"], []).append(index)
    keys = list(by_district)
    if not keys:
        return {"low": None, "high": None, "draws": 0}
    rng = random.Random(SEED)
    samples = []
    for _ in range(DRAWS):
        picked = [keys[rng.randrange(len(keys))] for _ in keys]
        indexes = [item for key in picked for item in by_district[key]]
        value = value_fn(indexes)
        if value is not None:
            samples.append(value)
    if not samples:
        return {"low": None, "high": None, "draws": 0}
    samples.sort()
    return {"low": _percent(samples, 2.5), "high": _percent(samples, 97.5), "draws": len(samples)}


def _fit_probs(train: list[dict], test: list[dict]) -> tuple[list[float], list[float], float]:
    x_train = np.array([[row[name] for name in FEATURES] for row in train], dtype=float)
    y_train = np.array([1 if row["loss_10"] else 0 for row in train])
    x_test = np.array([[row[name] for name in FEATURES] for row in test], dtype=float)
    rate = float(y_train.mean())
    if y_train.min() == y_train.max():
        constant = [rate] * len(test)
        return constant, constant, rate
    center = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale == 0] = 1.0
    logit = LogisticRegression(C=1.0, solver="lbfgs", max_iter=500)
    logit.fit((x_train - center) / scale, y_train)
    p_logit = logit.predict_proba((x_test - center) / scale)[:, 1]
    boosting = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=2,
        learning_rate=0.05,
        subsample=0.8,
        random_state=SEED,
    )
    boosting.fit(x_train, y_train)
    p_boost = boosting.predict_proba(x_test)[:, 1]
    return p_logit.tolist(), p_boost.tolist(), rate


def _subset(rows: list[dict], name: str | None, cuts) -> list[dict]:
    if name is None:
        return rows
    return [row for row in rows if row.get("band") == name or (row.get("band") is None and tertile(row["irrig_median"], cuts) == name)]


def _skill_on(rows: list[dict], probs: list[float], label_key: str) -> float | None:
    labels = [1 if row[label_key] else 0 for row in rows]
    refs = [row["rate"] for row in rows]
    return skill(brier(labels, probs), brier(labels, refs))


def _pack_score(rows: list[dict], probs: list[float], fired: list[bool] | None, label_key: str) -> dict:
    labels = [1 if row[label_key] else 0 for row in rows]
    refs = [row["rate"] for row in rows]
    model = brier(labels, probs)
    reference = brier(labels, refs)
    point = skill(model, reference)

    def on(indexes: list[int]) -> float | None:
        ys = [labels[i] for i in indexes]
        ps = [probs[i] for i in indexes]
        rs = [refs[i] for i in indexes]
        return skill(brier(ys, ps), brier(ys, rs))

    score = {
        "n": len(rows),
        "losses": sum(labels),
        "brier": model,
        "climatology_brier": reference,
        "skill": point,
        "interval": _interval(rows, on),
        "auc": roc_auc(labels, probs),
        "calibration": calibration(labels, probs),
    }
    if fired is not None:
        score["hit_rate"] = hit_rate(labels, fired)
        score["false_alarm_rate"] = false_alarm_rate(labels, fired)
        score["basis_risk"] = basis_risk_count(labels, fired)
    return score


def _choose(low_scores: dict[float, dict]) -> float:
    """Highest low-tertile skill. A tie uses the higher rainfall cut."""
    def sort_key(cut: float) -> tuple:
        value = low_scores[cut]["skill"]
        return (value is not None, value or 0.0, cut)
    return max(THRESHOLDS, key=sort_key)


def _attach_rate(rows: list[dict], rate: float) -> list[dict]:
    return [{**row, "rate": rate} for row in rows]


def _indexed_bundle(rows: list[dict], cuts) -> dict:
    """Same as _rule_bundle without a quadratic search."""
    positions = {id(row): index for index, row in enumerate(rows)}
    bundle = {}
    for cut in THRESHOLDS:
        fired = [row["season_pct"] < cut for row in rows]
        probs = [1.0 if flag else 0.0 for flag in fired]
        levels = {}
        for name in (None, "low", "mid", "high"):
            chosen = _subset(rows, name, cuts)
            if not chosen:
                continue
            chosen_probs = [probs[positions[id(row)]] for row in chosen]
            chosen_fired = [fired[positions[id(row)]] for row in chosen]
            levels["all" if name is None else name] = _pack_score(chosen, chosen_probs, chosen_fired, "loss_10")
        bundle[cut] = levels
    return bundle


def _model_bundle(rows: list[dict], probs: list[float], cuts) -> dict:
    positions = {id(row): index for index, row in enumerate(rows)}
    levels = {}
    for name in (None, "low", "mid", "high"):
        chosen = _subset(rows, name, cuts)
        if not chosen:
            continue
        chosen_probs = [probs[positions[id(row)]] for row in chosen]
        levels["all" if name is None else name] = _pack_score(chosen, chosen_probs, None, "loss_10")
    return levels


def _sensitivity(rows: list[dict], cut: float) -> dict:
    fired = [row["season_pct"] < cut for row in rows]
    probs = [1.0 if flag else 0.0 for flag in fired]
    found = {}
    for key in ("loss_5", "loss_15"):
        found[key] = _pack_score(rows, probs, fired, key)
    return found


def _misses(rows: list[dict], cut: float, limit: int = 10) -> list[dict]:
    missed = [row for row in rows if row["loss_10"] and not (row["season_pct"] < cut)]
    missed.sort(key=lambda row: (row["gap"], row["year"], row["district_id"]))
    return missed[:limit]


def _scheme(rows: list[dict], rate_rows: list[dict]) -> dict:
    cuts = tertile_cuts(rate_rows)
    # rate_rows is the training set used only to set tertile cuts.
    # The scored rows already carry their fold's climatology rate.
    rules = _indexed_bundle(rows, cuts)
    best = _choose({cut: rules[cut].get("low", rules[cut]["all"]) for cut in THRESHOLDS})
    return {"cuts": cuts, "rules": rules, "best": best}


def temporal_predictions(source: list[dict]) -> tuple[list[dict], list[dict], list[float], list[float]]:
    train, test = temporal_fold(source)
    p_logit, p_boost, rate = _fit_probs(train, test)
    cuts = tertile_cuts(train)
    scored = [{**row, "rate": rate, "band": tertile(row["irrig_median"], cuts)} for row in test]
    return train, scored, p_logit, p_boost


def spatial_predictions(source: list[dict]) -> tuple[list[dict], list[float], list[float]]:
    states = sorted({row["state"] for row in source})
    scored: list[dict] = []
    p_logit: list[float] = []
    p_boost: list[float] = []
    for state in states:
        train, test = spatial_fold(source, state)
        if len(train) < 20 or len(test) < 5:
            continue
        print(f"spatial {state}: train {len(train)} test {len(test)}", flush=True)
        fold_logit, fold_boost, rate = _fit_probs(train, test)
        cuts = tertile_cuts(train)
        scored.extend({**row, "rate": rate, "band": tertile(row["irrig_median"], cuts)} for row in test)
        p_logit.extend(fold_logit)
        p_boost.extend(fold_boost)
    return scored, p_logit, p_boost


def verdict(temporal_rules: dict, spatial_rules: dict) -> str:
    def clears(rules: dict, band: str) -> bool:
        score = rules["rules"][rules["best"]].get(band)
        if not score:
            return False
        low = score["interval"]["low"]
        return low is not None and low > 0

    low_ok = clears(temporal_rules, "low") and clears(spatial_rules, "low")
    high_ok = clears(temporal_rules, "high") and clears(spatial_rules, "high")
    if low_ok and high_ok:
        return "support a rainfall trigger"
    if low_ok:
        return "supports only where rainfed"
    return "does not support"


def _num(value, digits: int = 3) -> str:
    if value is None:
        return "missing"
    return f"{value:.{digits}f}"


def _line(score: dict) -> str:
    interval = score["interval"]
    extra = ""
    if "hit_rate" in score:
        extra = (
            f" hit {_num(score['hit_rate'])}"
            f" false-alarm {_num(score['false_alarm_rate'])}"
            f" basis-risk {score['basis_risk']}"
        )
    return (
        f"n {score['n']} losses {score['losses']}"
        f" brier {_num(score['brier'])}"
        f" skill {_num(score['skill'])}"
        f" interval {_num(interval['low'])} to {_num(interval['high'])}"
        f" auc {_num(score['auc'])}{extra}"
    )


def render(report: dict) -> str:
    lines = [
        "Trigger study on the Mendeley ICRISAT district file",
        "Design locked 2026-11-25 15:46 UTC+8, before these numbers were computed.",
        "DOI 10.17632/ywp3y5j9vv.1. CC BY 4.0. Unapportioned districts, 1990-2015.",
        f"Clean rows with rice, June-September rain, and an irrigation share: {report['clean_n']}.",
        f"Temporal train rows {report['train_n']}, test rows {report['test_n']}.",
        f"Spatial test rows {report['spatial_n']}.",
        "",
        f"Verdict: {report['verdict']}.",
        f"Best rainfall cut, temporal low-irrigation tertile: {int(report['temporal']['best'] * 100)} percent of the district normal.",
        f"Best rainfall cut, spatial low-irrigation tertile: {int(report['spatial']['best'] * 100)} percent of the district normal.",
        "The current Nueva Ecija payment line is about 80 percent of that site's long-run mean. It was not refit.",
        "",
    ]
    for scheme_name in ("temporal", "spatial"):
        scheme = report[scheme_name]
        lines.append(scheme_name.upper())
        for cut in THRESHOLDS:
            lines.append(f"Rule {int(cut * 100)} percent")
            for band in ("all", "low", "mid", "high"):
                score = scheme["rules"][cut].get(band)
                if score:
                    lines.append(f"  {band}: {_line(score)}")
        for model_name in ("logistic", "boosting"):
            lines.append(model_name)
            for band in ("all", "low", "mid", "high"):
                score = scheme[model_name].get(band)
                if score:
                    lines.append(f"  {band}: {_line(score)}")
        lines.append("Calibration of the best rule, all test rows")
        best = scheme["rules"][scheme["best"]]["all"]
        for row in best["calibration"]:
            lines.append(
                f"  n {row['n']} predicted {_num(row['mean_predicted'])} observed {_num(row['observed_rate'])}"
            )
        lines.append("Sensitivity of that same cut, all test rows, labels -5% and -15%")
        for key, score in scheme["sensitivity"].items():
            lines.append(f"  {key}: {_line(score)}")
        lines.append("Worst missed loss years in the low-irrigation tertile")
        if not scheme["misses"]:
            lines.append("  none")
        for row in scheme["misses"]:
            lines.append(
                f"  {row['year']} {row['state']} {row['name']} gap {_num(row['gap'], 1)} percent"
                f" season {_num(row['season_pct'] * 100, 1)} percent of normal"
            )
        lines.append("")
    lines.append(
        "Limits: India, not Nueva Ecija. District averages, not one farm. Unapportioned boundaries change over these years. "
        "The yield is the annual rice crop, not a June-September harvest. Gross irrigated area is not rice irrigation. "
        "Pests, floods, prices, policy, and older records can move yield. The bootstrap does not refit the model."
    )
    return "\n".join(lines) + "\n"


def run(workbook: Path, table_path: Path) -> dict:
    rows = load_workbook(workbook)
    write_csv(rows, table_path)
    usable = read_csv(table_path)
    usable = [row for row in usable if row["irrig_share"] is not None and row["season_mm"] is not None and row["yield_kg_ha"] is not None and row["yield_kg_ha"] > 0]
    train, temporal_rows, p_logit, p_boost = temporal_predictions(usable)
    temporal_rules_rows = temporal_rows
    temporal = _scheme(temporal_rules_rows, train)
    temporal["logistic"] = _model_bundle(temporal_rows, p_logit, tertile_cuts(train))
    temporal["boosting"] = _model_bundle(temporal_rows, p_boost, tertile_cuts(train))
    low_rows = _subset(temporal_rows, "low", tertile_cuts(train))
    temporal["sensitivity"] = _sensitivity(temporal_rows, temporal["best"])
    temporal["misses"] = _misses(low_rows, temporal["best"])

    spatial_rows, s_logit, s_boost = spatial_predictions(usable)
    # Tertile cuts for the spatial pool use every district's early-year median,
    # taken from a temporal training build so the cuts are not fit on test years.
    spatial = _scheme(spatial_rows, train)
    spatial["logistic"] = _model_bundle(spatial_rows, s_logit, tertile_cuts(train))
    spatial["boosting"] = _model_bundle(spatial_rows, s_boost, tertile_cuts(train))
    spatial_low = _subset(spatial_rows, "low", tertile_cuts(train))
    spatial["sensitivity"] = _sensitivity(spatial_rows, spatial["best"])
    spatial["misses"] = _misses(spatial_low, spatial["best"])
    return {
        "clean_n": len(usable),
        "train_n": len(train),
        "test_n": len(temporal_rows),
        "spatial_n": len(spatial_rows),
        "temporal": temporal,
        "spatial": spatial,
        "verdict": verdict({"rules": temporal["rules"], "best": temporal["best"]}, {"rules": spatial["rules"], "best": spatial["best"]}),
    }

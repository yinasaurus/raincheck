"""Local reasons for one score.

This is not SHAP. For each input we swap that input back to the training-set
median, rescore, and record how much the drought probability moves. The
pieces do not add up to the score. They only answer "which inputs, if they
looked typical, would have changed this probability the most?"
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def positive_probability(model, rows: pd.DataFrame) -> np.ndarray:
    if list(getattr(model, "classes_", [])) != [0, 1]:
        raise ValueError("model must be a binary classifier with classes [0, 1]")
    return model.predict_proba(rows)[:, 1]


def top_factors(
    model,
    row: pd.Series,
    medians: pd.Series,
    feature_columns: list[str],
    limit: int = 3,
) -> list[dict]:
    base_frame = pd.DataFrame([row[feature_columns]], columns=feature_columns)
    base = float(positive_probability(model, base_frame)[0])
    factors: list[dict] = []
    for name in feature_columns:
        swapped = base_frame.copy()
        typical = float(medians[name])
        swapped.iloc[0, swapped.columns.get_loc(name)] = typical
        swapped_probability = float(positive_probability(model, swapped)[0])
        factors.append(
            {
                "feature": name,
                "value": float(row[name]),
                "typical_value": typical,
                "probability_delta": base - swapped_probability,
                "method": "one_at_a_time_vs_training_median",
            }
        )
    factors.sort(key=lambda item: abs(item["probability_delta"]), reverse=True)
    return factors[:limit]

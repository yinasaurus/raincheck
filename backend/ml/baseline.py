"""Rule of thumb used as the comparison point for the trained model.

Call drought when rainfall so far in the season is under 75% of the
leave-one-year-out normal for this same week. The probability is a straight
line anchored at 0.15 when rainfall is exactly normal and 0.50 at 75% of
normal, then clipped to [0.02, 0.98] so a later ROC calculation never sees
a hard 0 or 1.

0.15 is only the anchor of this rule (near the chance that a normal
distribution is below -1). It is not estimated from our labels, and the
line is not fit to them. Accuracy uses `pct < 0.75`, which matches
"unclipped probability > 0.5".
"""

from __future__ import annotations

import numpy as np

PROBABILITY_AT_NORMAL = 0.15
DROUGHT_PCT = 0.75
# Rise from 0.15 at 100% of normal to 0.50 at 75% of normal.
SLOPE_PER_PCT_SHORTFALL = (0.50 - PROBABILITY_AT_NORMAL) / (1.0 - DROUGHT_PCT)


def baseline_probability(cumulative_pct_of_normal: np.ndarray) -> np.ndarray:
    pct = np.asarray(cumulative_pct_of_normal, dtype=float)
    raw = PROBABILITY_AT_NORMAL + (1.0 - pct) * SLOPE_PER_PCT_SHORTFALL
    return np.clip(raw, 0.02, 0.98)


def baseline_calls_drought(cumulative_pct_of_normal: np.ndarray) -> np.ndarray:
    pct = np.asarray(cumulative_pct_of_normal, dtype=float)
    return pct < DROUGHT_PCT

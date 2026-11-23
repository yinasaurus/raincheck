"""Proxy drought labels from rainfall. There is no yield dataset behind these flags.

Seasonal SPI used here:
1. Take June-October (or whatever contiguous season is configured) rainfall totals
   for every complete year.
2. Fit a two-parameter gamma distribution by method of moments, location fixed at 0.
   shape = mean^2 / sample_variance, scale = sample_variance / mean.
3. SPI = inverse-normal of that gamma's cumulative probability.
4. drought_stress is true when SPI <= threshold (default -1.0).

Probabilities are clipped to [1e-6, 1-1e-6] before the inverse normal so a
single extreme year cannot produce an infinite SPI.

This is not the SPI published by a meteorological service (those use a longer
record and a fixed software stack), and it is not a crop-failure label.
A season is dropped from the fit when more than 10% of its days are missing
or have no rainfall value. Each labeled year is inside its own reference
period; with about 25 years, leaving one year out of the mean moves SPI only
slightly, and the simpler full-sample fit is the one we document.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import gamma, norm

SPI_CLIP = 1e-6
MIN_COMPLETE_FRACTION = 0.9


def seasonal_spi(totals_mm: np.ndarray) -> tuple[np.ndarray, bool]:
    """Return SPI values and whether the gamma fit was defined."""
    totals = np.asarray(totals_mm, dtype=float)
    if totals.ndim != 1 or len(totals) < 3:
        raise ValueError("SPI needs at least 3 seasonal totals")
    if np.isnan(totals).any() or np.any(totals < 0):
        raise ValueError("seasonal totals must be finite and non-negative")

    mean = float(totals.mean())
    variance = float(totals.var(ddof=1))
    if mean <= 0 or variance <= 1e-9:
        return np.zeros(len(totals), dtype=float), False

    shape = (mean * mean) / variance
    scale = variance / mean
    cdf = gamma.cdf(totals, a=shape, loc=0.0, scale=scale)
    cdf = np.clip(cdf, SPI_CLIP, 1.0 - SPI_CLIP)
    return norm.ppf(cdf), True


def label_seasons(season_rows: pd.DataFrame, spi_threshold: float = -1.0) -> pd.DataFrame:
    """Add SPI, percent of average, and the proxy drought flag.

    `drought_stress` is True/False for complete seasons and null when the
    season was left out of the fit. Callers must not treat null as False.
    """
    if "year" not in season_rows.columns or "rainfall_mm" not in season_rows.columns:
        raise ValueError("season rows need year and rainfall_mm")

    frame = season_rows.copy().reset_index(drop=True)
    frame["excluded_reason"] = None
    complete = []
    for index, row in frame.iterrows():
        reason = _exclusion_reason(row)
        frame.at[index, "excluded_reason"] = reason
        if reason is None:
            complete.append(index)

    frame["spi"] = np.nan
    frame["spi_defined"] = False
    frame["long_term_average_mm"] = np.nan
    frame["rainfall_pct_of_lta"] = np.nan
    frame["drought_stress"] = pd.Series([pd.NA] * len(frame), dtype="boolean")

    if len(complete) < 3:
        return frame

    totals = frame.loc[complete, "rainfall_mm"].to_numpy(dtype=float)
    spi, defined = seasonal_spi(totals)
    average = float(totals.mean())
    frame.loc[complete, "spi"] = spi
    frame.loc[complete, "spi_defined"] = defined
    frame.loc[complete, "long_term_average_mm"] = average
    frame.loc[complete, "rainfall_pct_of_lta"] = totals / average
    if defined:
        frame.loc[complete, "drought_stress"] = spi <= spi_threshold
    else:
        frame.loc[complete, "drought_stress"] = False
    return frame


def is_drought(spi: float, threshold: float = -1.0) -> bool:
    """The threshold check on its own, so tests can pin -1.0 without refitting."""
    if spi != spi:
        raise ValueError("spi must be a finite number")
    return float(spi) <= threshold


def _exclusion_reason(row: pd.Series) -> str | None:
    rainfall = row["rainfall_mm"]
    if rainfall is None or (isinstance(rainfall, float) and np.isnan(rainfall)):
        return "missing_rainfall"
    expected = int(row["expected_days"]) if "expected_days" in row and pd.notna(row["expected_days"]) else None
    observed = row["precip_obs_days"] if "precip_obs_days" in row else row.get("n_days")
    if expected and observed is not None and float(observed) < MIN_COMPLETE_FRACTION * expected:
        return "incomplete_season"
    return None

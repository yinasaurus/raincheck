"""The drought flag is a documented rainfall proxy, not a yield label."""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import gamma, norm

from ml.labels import SPI_CLIP, is_drought, label_seasons, seasonal_spi


def _rows(values: list[tuple[int, float]], observed_days: int = 153, expected_days: int = 153):
    return pd.DataFrame(
        [
            {
                "year": year,
                "rainfall_mm": rainfall,
                "expected_days": expected_days,
                "precip_obs_days": observed_days,
                "n_days": observed_days,
            }
            for year, rainfall in values
        ]
    )


def test_threshold_is_inclusive_at_minus_one():
    assert is_drought(-1.0)
    assert is_drought(-1.01)
    assert not is_drought(-0.999)


def test_spi_matches_method_of_moments_gamma():
    totals = np.array([80, 100, 120, 90, 110, 70, 95, 105], dtype=float)
    spi, defined = seasonal_spi(totals)
    mean = float(totals.mean())
    variance = float(totals.var(ddof=1))
    shape = (mean * mean) / variance
    scale = variance / mean
    expected = norm.ppf(np.clip(gamma.cdf(totals, a=shape, loc=0.0, scale=scale), SPI_CLIP, 1 - SPI_CLIP))
    assert defined
    np.testing.assert_allclose(spi, expected)
    order = np.argsort(totals)
    assert np.all(np.diff(spi[order]) >= -1e-9)


def test_dry_outlier_is_labeled_and_a_normal_year_is_not():
    values = [(2000 + index, 100.0) for index in range(20)] + [(2020, 40.0)]
    labeled = label_seasons(_rows(values), spi_threshold=-1.0)
    dry = labeled[labeled["year"] == 2020].iloc[0]
    normal = labeled[labeled["year"] == 2005].iloc[0]
    assert dry["spi"] < normal["spi"]
    assert bool(dry["drought_stress"])
    assert not bool(normal["drought_stress"])
    assert dry["spi"] <= -1.0
    assert labeled["drought_stress"].tolist() == [is_drought(value) for value in labeled["spi"]]


def test_constant_rainfall_does_not_invent_a_drought():
    values = [(2000 + index, 100.0) for index in range(5)]
    labeled = label_seasons(_rows(values), spi_threshold=-1.0)
    assert not bool(labeled["spi_defined"].iloc[0])
    assert not labeled["drought_stress"].any()


def test_incomplete_season_is_left_out_of_the_average():
    complete = [(2000 + index, 100.0) for index in range(5)]
    frame = _rows(complete)
    incomplete = pd.DataFrame(
        [
            {
                "year": 2010,
                "rainfall_mm": 10.0,
                "expected_days": 153,
                "precip_obs_days": 100,
                "n_days": 100,
            }
        ]
    )
    labeled = label_seasons(pd.concat([frame, incomplete], ignore_index=True), spi_threshold=-1.0)
    held_out = labeled[labeled["year"] == 2010].iloc[0]
    assert held_out["excluded_reason"] == "incomplete_season"
    assert pd.isna(held_out["drought_stress"])
    kept = labeled[labeled["year"] != 2010]
    assert kept["long_term_average_mm"].iloc[0] == pytest.approx(100)

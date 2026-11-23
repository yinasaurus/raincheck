"""Plain-language risk text. No network call and no API key.

The optional LLM wording can be added later behind this same function.
Until then every explanation is this template, so the demo works offline.
"""

from __future__ import annotations


def risk_band(score: float) -> str:
    """Display bands only. 0.33 and 0.66 are not agronomic thresholds."""
    if score < 0.33:
        return "low"
    if score < 0.66:
        return "medium"
    return "high"


def explain_risk(
    region_name: str,
    crop: str,
    season_year: int,
    season_status: str,
    risk_score: float | None,
    factors: list[dict],
    trigger_rainfall_mm: int,
    observed_rainfall_mm: float | None = None,
    trigger_fired: bool | None = None,
    spi: float | None = None,
    drought_proxy: bool | None = None,
    score_source: str | None = None,
) -> str:
    owed = (
        "The score does not change what is owed. "
        f"A payment change is allowed only when measured rainfall for the whole season "
        f"is below the agreed {trigger_rainfall_mm} mm."
    )
    if season_status == "not_started":
        return (
            f"The {season_year} wet season for {crop} in {region_name} has not started. "
            "RainCheck does not invent a risk number before rainfall is observed. "
            + owed
        )
    if risk_score is None:
        return (
            f"There is not yet a full week of {season_year} season data to score. "
            + owed
        )

    band = risk_band(risk_score)
    percent = f"{risk_score * 100:.0f}%"
    if season_status == "complete":
        opening = (
            f"The {season_year} wet season for {crop} in {region_name} is already over. "
            f"Looking back at the last full week, the model put the chance of a drought-stress "
            f"season at {percent} ({band}). That number is a look back, not a forecast."
        )
    else:
        opening = (
            f"Partway through the {season_year} wet season for {crop} in {region_name}, "
            f"the model puts the chance that the season ends in drought stress at {percent} ({band})."
        )

    sentences = [opening]
    sentences.append(
        "Drought stress here means a rainfall proxy (seasonal SPI at or below -1), "
        "not a measured crop failure. The low, medium, and high bands split at 33% and 66% "
        "for the screen only."
    )
    factor_text = _factor_sentence(factors)
    if factor_text:
        sentences.append(factor_text)
    if score_source == "leave_one_season_out":
        sentences.append(
            "This probability is from a model that did not train on this season."
        )
    elif score_source == "served_model":
        sentences.append(
            "This probability is from the model trained on the historical seasons. This season was not one of them."
        )
    sentences.append(owed)
    if season_status == "complete" and observed_rainfall_mm is not None and trigger_fired is not None:
        comparison = "below" if trigger_fired else "not below"
        label = "yes" if drought_proxy else "no"
        spi_text = "n/a" if spi is None else f"{spi:.2f}"
        sentences.append(
            f"Observed season rainfall was {observed_rainfall_mm:.0f} mm, which is {comparison} "
            f"the agreed line. Proxy drought label: {label} (SPI {spi_text})."
        )
    elif season_status == "in_progress":
        sentences.append(
            "The rainfall trigger is not checked until the season window has closed. "
            "Rain so far is not compared with the full-season line."
        )
    return " ".join(sentences)


def _factor_sentence(factors: list[dict]) -> str:
    pieces = []
    for factor in factors:
        if abs(factor.get("probability_delta", 0.0)) < 0.01:
            continue
        text = _describe_factor(factor)
        if text:
            pieces.append(text)
        if len(pieces) == 3:
            break
    if not pieces:
        return ""
    return "The inputs that moved this score the most: " + "; ".join(pieces) + "."


def _describe_factor(factor: dict) -> str:
    name = factor["feature"]
    value = float(factor["value"])
    delta = float(factor["probability_delta"])
    if delta > 0:
        direction = "raised"
    elif delta < 0:
        direction = "lowered"
    else:
        direction = "barely changed"
    if name == "cumulative_pct_of_normal":
        return (
            f"rainfall so far is {value * 100:.0f}% of the usual amount for this point in the season, "
            f"which {direction} the score"
        )
    if name == "cumulative_rainfall_mm":
        return f"the running rainfall total is {value:.0f} mm, which {direction} the score"
    if name == "recent_rainfall_mm":
        return f"the latest week had {value:.0f} mm of rain, which {direction} the score"
    if name == "recent_vs_normal":
        return (
            f"the latest week was {value * 100:.0f}% of a usual week, which {direction} the score"
        )
    if name == "rainfall_trend_mm":
        return f"the week-to-week rainfall change is {value:.0f} mm, which {direction} the score"
    if name == "temp_mean_to_date":
        return f"the average temperature so far is {value:.1f}°C, which {direction} the score"
    if name == "temp_max_to_date":
        return f"the hottest day so far is {value:.1f}°C, which {direction} the score"
    if name == "hot_days_to_date":
        return f"there have been {value:.0f} days at or above 35°C, which {direction} the score"
    if name == "fraction_elapsed":
        return f"the season is {value * 100:.0f}% of the way through, which {direction} the score"
    return ""

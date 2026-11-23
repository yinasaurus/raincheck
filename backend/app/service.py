"""Read the cache and the saved model. No training happens inside a request."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import joblib
import pandas as pd

from app.explanations import explain_risk, risk_band
from data.aggregate import (
    aggregate_monthly,
    aggregate_weekly,
    calendar_season_weeks,
    prepare_daily,
    season_bounds,
    season_totals,
    season_week_buckets,
)
from data.paths import DAILY_CSV, LOO_SCORES_PATH, METRICS_PATH, MODEL_PATH, REGION_PATH
from data.trigger import agreed_trigger_mm, round_mm, trigger_fires
from ml.baseline import baseline_probability
from ml.explain import positive_probability, top_factors
from ml.features import buckets_for_years, build_feature_frame
from ml.labels import label_seasons

LIMITATIONS = [
    "A blockchain record can prove what was written down. It cannot prove the weather feed was true (the oracle problem).",
    "Weather at this grid point is not the same as weather on one farm (basis risk).",
    "This is a prototype and a simulation. It is not a regulated lending product.",
]


class NotReady(RuntimeError):
    """Raised when the cache or the model file is missing."""


class SeasonNotFound(LookupError):
    pass


class RainCheckService:
    def __init__(self) -> None:
        self.region = json.loads(REGION_PATH.read_text(encoding="utf-8"))
        self.months = [int(month) for month in self.region["planting_season_months"]]
        self.season_weeks = calendar_season_weeks(self.months)
        self.heat = float(self.region["heat_day_celsius"])
        self.threshold = float(self.region["drought_label"]["threshold"])
        self.daily = prepare_daily(pd.read_csv(DAILY_CSV)) if DAILY_CSV.exists() else None
        self.bundle = joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None
        self.metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8")) if METRICS_PATH.exists() else None
        self.loo_scores = {}
        if LOO_SCORES_PATH.exists():
            self.loo_scores = json.loads(LOO_SCORES_PATH.read_text(encoding="utf-8")).get("scores", {})
        self.labeled = None
        self.labels: dict[int, bool] = {}
        self.buckets: dict[int, pd.DataFrame] = {}
        self.trigger_mm: int | None = None
        self.trigger_source = "pct_of_long_term_average"
        if self.daily is not None:
            self._prepare_tables()

    def _prepare_tables(self) -> None:
        self.labeled = label_seasons(season_totals(self.daily, self.months), spi_threshold=self.threshold)
        complete = self.labeled[self.labeled["drought_stress"].notna()]
        self.labels = {int(row.year): bool(row.drought_stress) for row in complete.itertuples()}
        years = sorted(set(self.labeled["year"].astype(int)).union(self.labels))
        self.buckets = buckets_for_years(self.daily, years, self.months, self.heat)
        if len(complete) == 0:
            return
        average = float(complete["rainfall_mm"].mean())
        override = self.region["trigger"].get("rainfall_mm")
        self.trigger_source = "explicit_config" if override is not None else "pct_of_long_term_average"
        self.trigger_mm = agreed_trigger_mm(
            average,
            float(self.region["trigger"]["pct_of_long_term_average"]),
            override_mm=None if override is None else float(override),
        )

    def require_weather(self) -> None:
        if self.daily is None or self.labeled is None or self.trigger_mm is None:
            raise NotReady("Weather cache is missing. From backend/, run: python -m ml.train")

    def require_model(self) -> None:
        self.require_weather()
        if self.bundle is None:
            raise NotReady("Model file is missing. From backend/, run: python -m ml.train")

    def region_payload(self) -> dict:
        self.require_weather()
        complete = self.labeled[self.labeled["drought_stress"].notna()]
        seasons = []
        for row in self.labeled.sort_values("year").itertuples():
            drought = None if pd.isna(row.drought_stress) else bool(row.drought_stress)
            seasons.append(
                {
                    "year": int(row.year),
                    "rainfall_mm": None if pd.isna(row.rainfall_mm) else round(float(row.rainfall_mm), 1),
                    "long_term_average_mm": None
                    if pd.isna(row.long_term_average_mm)
                    else round(float(row.long_term_average_mm), 1),
                    "rainfall_pct_of_lta": None
                    if pd.isna(row.rainfall_pct_of_lta)
                    else round(float(row.rainfall_pct_of_lta), 3),
                    "spi": None if pd.isna(row.spi) else round(float(row.spi), 3),
                    "drought_stress": drought,
                    "excluded_reason": row.excluded_reason,
                    "label_is_proxy": True,
                }
            )
        return {
            "name": self.region["name"],
            "country": self.region["country"],
            "latitude": self.region["latitude"],
            "longitude": self.region["longitude"],
            "timezone": self.region["timezone"],
            "crop": self.region["crop"],
            "season_name": self.region["season_name"],
            "planting_season_months": self.months,
            "drought_label": self.region["drought_label"],
            "trigger": {
                "proposed_trigger_rainfall_mm": self.trigger_mm,
                "pct_of_long_term_average": self.region["trigger"]["pct_of_long_term_average"],
                "source": self.trigger_source,
                "window": self.region["trigger"]["window"],
                "comparison": "observed seasonal rainfall, rounded half-up to a whole millimetre, is strictly below the trigger",
                "uses_model_score": False,
                "note": (
                    "This millimetre value is the proposed demo strike. A loan stores the number "
                    "at creation. Later seasons do not silently rewrite it."
                ),
            },
            "history": {
                "complete_seasons": int(len(complete)),
                "long_term_average_mm": round(float(complete["rainfall_mm"].mean()), 1),
                "proxy_drought_years": [
                    int(year) for year in complete.loc[complete["drought_stress"].astype(bool), "year"].tolist()
                ],
                "note": "proxy_drought_years come from the SPI rule. They are not records of crop failure.",
            },
            "seasons": seasons,
            "limitations": LIMITATIONS,
        }

    def observed_weather(self, start: date, end: date, resolution: str) -> dict:
        self.require_weather()
        if resolution not in {"daily", "weekly", "monthly"}:
            raise ValueError("resolution must be daily, weekly, or monthly")
        if end < start:
            raise ValueError("`to` must be on or after `from`")
        if resolution == "daily":
            frame = self.daily[(self.daily["date"] >= pd.Timestamp(start)) & (self.daily["date"] <= pd.Timestamp(end))]
            rows = [
                {
                    "date": row.date.date().isoformat(),
                    "precipitation_mm": _round_or_none(row.precipitation_mm, 2),
                    "temp_mean_c": _round_or_none(row.temp_mean_c, 2),
                    "temp_max_c": _round_or_none(row.temp_max_c, 2),
                    "temp_min_c": _round_or_none(row.temp_min_c, 2),
                }
                for row in frame.itertuples()
            ]
        elif resolution == "weekly":
            weekly = aggregate_weekly(self.daily)
            rows = [
                row
                for row in weekly.to_dict(orient="records")
                if row["week_end"] >= start.isoformat() and row["week_start"] <= end.isoformat()
            ]
            rows = [_round_weather_row(row) for row in rows]
        else:
            monthly = aggregate_monthly(self.daily)
            rows = [
                row
                for row in monthly.to_dict(orient="records")
                if not (date(int(row["year"]), int(row["month"]), 1) > end)
                and season_month_end(int(row["year"]), int(row["month"])) >= start
            ]
            rows = [_round_weather_row(row) for row in rows]
        return {
            "region": self.region["name"],
            "resolution": resolution,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "source": "Open-Meteo Archive API (on-disk cache)",
            "attribution": "Weather data by Open-Meteo.com, CC-BY 4.0",
            "rows": rows,
        }

    def risk(self, today: date | None = None) -> dict:
        self.require_model()
        today = today or date.today()
        year, status = _season_status(today, self.months)
        data_note = None
        if status == "complete" and year not in self.buckets:
            earlier = [item for item in self.labels if item < year]
            if not earlier:
                raise SeasonNotFound(f"No season data is available for {year}.")
            year = max(earlier)
            data_note = (
                f"The {today.year} season is not in the weather cache yet. "
                f"Showing the latest labeled season, {year}."
            )

        trigger_mm = self.trigger_mm
        assert trigger_mm is not None
        if status == "not_started":
            return self._risk_body(
                year=year,
                status=status,
                score=None,
                factors=[],
                scored_week=None,
                observed=None,
                trigger_fired=None,
                trigger_pending=True,
                data_note=data_note,
                today=today,
            )

        frame = self._features_for(year)
        if status == "in_progress":
            # A week is usable only after its last day. The current week is still filling up,
            # and scoring it would make "this week" look drier than it is.
            frame = frame[frame["week_end"].map(date.fromisoformat) < today]
        if frame.empty:
            return self._risk_body(
                year=year,
                status="awaiting_first_week",
                score=None,
                factors=[],
                scored_week=None,
                observed=self._season_row(year),
                trigger_fired=None,
                trigger_pending=True,
                data_note=data_note,
                today=today,
            )

        row = frame.sort_values("week_index").iloc[-1]
        score, factors, baseline_score, score_source = self._score_known_week(year, int(row["week_index"]), row)
        observed = self._season_row(year)
        trigger_fired = None
        trigger_pending = True
        if status == "complete" and observed is not None and observed.get("rainfall_mm") is not None:
            if observed.get("excluded_reason") is None:
                trigger_fired = trigger_fires(observed["rainfall_mm"], trigger_mm)
                trigger_pending = False
        return self._risk_body(
            year=year,
            status=status,
            score=score,
            factors=factors,
            scored_week=row,
            observed=observed,
            trigger_fired=trigger_fired,
            trigger_pending=trigger_pending,
            data_note=data_note,
            today=today,
            baseline_score=baseline_score,
            score_source=score_source,
        )

    def simulate(self, year: int) -> dict:
        self.require_model()
        if year not in self.buckets:
            raise SeasonNotFound(f"No weather for {year} in the cache.")
        buckets = self.buckets[year].sort_values("week_index")
        features = self._features_for(year).set_index("week_index")
        observed = self._season_row(year)
        season_complete = observed is not None and observed.get("excluded_reason") is None and observed.get("rainfall_mm") is not None
        season_total = None if not season_complete else float(observed["rainfall_mm"])
        trigger_mm = int(self.trigger_mm)
        fired = bool(trigger_fires(season_total, trigger_mm)) if season_complete else False
        weeks = []
        carried_score = None
        carried_baseline = None
        carried_source = None
        carried_factors: list[dict] = []
        cumulative = 0.0
        for bucket in buckets.itertuples():
            rainfall = 0.0 if pd.isna(bucket.precipitation_mm) else float(bucket.precipitation_mm)
            cumulative += rainfall
            week_index = int(bucket.week_index)
            carried = False
            if week_index in features.index and not bool(bucket.partial):
                score, factors, baseline_score, score_source = self._score_known_week(
                    year, week_index, features.loc[week_index]
                )
                carried_score = score
                carried_baseline = baseline_score
                carried_source = score_source
                carried_factors = factors
            else:
                score = carried_score
                baseline_score = carried_baseline
                score_source = carried_source
                factors = carried_factors
                carried = carried_score is not None
            is_last = week_index == int(buckets["week_index"].max())
            weeks.append(
                {
                    "week_index": week_index,
                    "week_start": bucket.week_start,
                    "week_end": bucket.week_end,
                    "partial": bool(bucket.partial),
                    "rainfall_mm": round(rainfall, 2),
                    "cumulative_rainfall_mm": round(cumulative, 2),
                    "risk_score": None if score is None else round(score, 4),
                    "baseline_score": None if baseline_score is None else round(baseline_score, 4),
                    "score_source": score_source if score is not None else None,
                    "risk_band": None if score is None else risk_band(score),
                    "risk_carried_forward": carried,
                    "top_factors": factors,
                    "trigger_fired": bool(fired and is_last and season_complete),
                    "trigger_pending": not (is_last and season_complete),
                }
            )
        label = None
        if observed is not None:
            label = {
                "spi": observed.get("spi"),
                "rainfall_pct_of_lta": observed.get("rainfall_pct_of_lta"),
                "drought_stress": observed.get("drought_stress"),
                "excluded_reason": observed.get("excluded_reason"),
                "proxy": True,
                "definition": self.region["drought_label"]["definition"],
            }
        return {
            "year": year,
            "region": self.region["name"],
            "crop": self.region["crop"],
            "season_months": self.months,
            "season_rainfall_mm": None if season_total is None else round(season_total, 2),
            "label": label,
            "trigger": {
                "trigger_rainfall_mm": trigger_mm,
                "observed_rainfall_mm": None if season_total is None else round(season_total, 2),
                "observed_mm": None if season_total is None else round_mm(season_total),
                "fired": fired,
                "pending": not season_complete,
                "uses_model_score": False,
                "rule": "Fired only on the last step, and only if full-season observed rainfall is strictly below the trigger.",
            },
            "weeks": weeks,
            "disclaimer": (
                "Replay of historical weather. The drought flag is a rainfall proxy (SPI), "
                "not a record of crop failure. The trigger uses the pre-agreed rainfall rule, "
                "not the model score. Scores on a past season are leave-one-season-out "
                "when that file is present, so the model being shown did not train on this year. "
                "Nothing here is a loan disbursement."
            ),
        }

    def _features_for(self, year: int) -> pd.DataFrame:
        # Historical years are left out of their own normal, matching training.
        # A year that is not in the labeled set (the live season) is compared
        # with every complete season.
        normal_years = sorted(self.labels)
        return build_feature_frame(
            self.buckets,
            include_years=[year],
            normal_years=normal_years,
            label_by_year=self.labels,
            season_weeks=self.season_weeks,
        )

    def _score_known_week(self, year: int, week_index: int, row: pd.Series):
        """Prefer the held-out score. The served model has already seen past seasons."""
        saved = (self.loo_scores.get(str(year)) or {}).get(str(week_index))
        if saved:
            return (
                float(saved["model_probability"]),
                saved.get("top_factors") or [],
                float(saved["baseline_probability"]),
                "leave_one_season_out",
            )
        score, factors = self._score_row(row)
        baseline = float(baseline_probability([float(row["cumulative_pct_of_normal"])])[0])
        return score, factors, baseline, "served_model"

    def _score_row(self, row: pd.Series) -> tuple[float, list[dict]]:
        columns = self.bundle["feature_columns"]
        frame = pd.DataFrame([row[columns]], columns=columns)
        score = float(positive_probability(self.bundle["model"], frame)[0])
        factors = top_factors(self.bundle["model"], row, self.bundle["medians"], columns, limit=3)
        return score, factors

    def _season_row(self, year: int) -> dict | None:
        matched = self.labeled[self.labeled["year"] == year]
        if matched.empty:
            return None
        row = matched.iloc[0]
        drought = None if pd.isna(row["drought_stress"]) else bool(row["drought_stress"])
        return {
            "year": year,
            "rainfall_mm": None if pd.isna(row["rainfall_mm"]) else float(row["rainfall_mm"]),
            "long_term_average_mm": None
            if pd.isna(row["long_term_average_mm"])
            else float(row["long_term_average_mm"]),
            "rainfall_pct_of_lta": None if pd.isna(row["rainfall_pct_of_lta"]) else float(row["rainfall_pct_of_lta"]),
            "spi": None if pd.isna(row["spi"]) else float(row["spi"]),
            "drought_stress": drought,
            "excluded_reason": None if pd.isna(row["excluded_reason"]) else row["excluded_reason"],
        }

    def _risk_body(
        self,
        year: int,
        status: str,
        score: float | None,
        factors: list[dict],
        scored_week: pd.Series | None,
        observed: dict | None,
        trigger_fired: bool | None,
        trigger_pending: bool,
        data_note: str | None,
        today: date,
        baseline_score: float | None = None,
        score_source: str | None = None,
    ) -> dict:
        observed_mm = None if observed is None else observed.get("rainfall_mm")
        spi = None if observed is None else observed.get("spi")
        drought = None if observed is None else observed.get("drought_stress")
        explanation = explain_risk(
            region_name=self.region["name"],
            crop=self.region["crop"],
            season_year=year,
            season_status=status if status != "awaiting_first_week" else "in_progress",
            risk_score=score,
            factors=factors,
            trigger_rainfall_mm=int(self.trigger_mm),
            observed_rainfall_mm=observed_mm if status == "complete" else None,
            trigger_fired=trigger_fired if status == "complete" else None,
            spi=spi if status == "complete" else None,
            drought_proxy=drought if status == "complete" else None,
            score_source=score_source,
        )
        headline = None
        if self.metrics is not None:
            by_week = self.metrics["evaluation"]["by_week"]
            week_12 = by_week.get("12", {})
            headline = {
                "protocol": self.metrics["evaluation"]["protocol"],
                "checkpoint_week": 12,
                "n_seasons": week_12.get("n_seasons"),
                "n_drought": week_12.get("n_drought"),
                "model": week_12.get("model"),
                "baseline": week_12.get("baseline"),
                "false_negatives": week_12.get("false_negatives"),
                "false_positives": week_12.get("false_positives"),
                "caveat": self.metrics["evaluation"]["small_sample_note"],
            }
        return {
            "region": self.region["name"],
            "crop": self.region["crop"],
            "season_year": year,
            "season_status": status,
            "as_of": None if scored_week is None else scored_week["week_end"],
            "requested_on": today.isoformat(),
            "data_note": data_note,
            "risk_score": None if score is None else round(score, 4),
            "baseline_score": None if baseline_score is None else round(baseline_score, 4),
            "score_source": score_source,
            "risk_band": None if score is None else risk_band(score),
            "risk_band_note": "Bands split at 0.33 and 0.66 for display. They are not agronomic standards.",
            "top_factors": factors,
            "explanation": explanation,
            "explanation_source": "template",
            "advisory_only": True,
            "observed": None
            if observed is None
            else {
                "season_rainfall_mm": _round_or_none(observed.get("rainfall_mm"), 1),
                "long_term_average_mm": _round_or_none(observed.get("long_term_average_mm"), 1),
                "rainfall_pct_of_average": _round_or_none(observed.get("rainfall_pct_of_lta"), 3),
                "spi": _round_or_none(observed.get("spi"), 3),
                "drought_proxy_label": observed.get("drought_stress"),
                "label_definition": self.region["drought_label"]["definition"],
                "excluded_reason": observed.get("excluded_reason"),
            },
            "trigger": {
                "trigger_rainfall_mm": self.trigger_mm,
                "observed_rainfall_mm": _round_or_none(observed_mm, 1) if status == "complete" else None,
                "fired": trigger_fired,
                "pending": trigger_pending,
                "uses_model_score": False,
                "rule": (
                    "Fired only if observed seasonal rainfall is strictly below the pre-agreed "
                    "trigger. The risk score cannot fire it."
                ),
            },
            "evaluation": headline,
            "limitations": LIMITATIONS,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


def _season_status(today: date, months: list[int]) -> tuple[int, str]:
    start, end = season_bounds(today.year, months)
    if today < start:
        return today.year, "not_started"
    if today > end:
        return today.year, "complete"
    return today.year, "in_progress"


def season_month_end(year: int, month: int) -> date:
    import calendar

    return date(year, month, calendar.monthrange(year, month)[1])


def _round_or_none(value, places: int):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return round(float(value), places)


def _round_weather_row(row: dict) -> dict:
    cleaned = {}
    for key, value in row.items():
        if isinstance(value, float):
            cleaned[key] = None if pd.isna(value) else round(value, 2)
        else:
            cleaned[key] = value
    return cleaned

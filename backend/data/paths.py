"""Paths that stay valid no matter which directory the process was started from."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REGION_PATH = BACKEND_ROOT / "region.json"
CACHE_DIR = BACKEND_ROOT / "data" / "cache"
DAILY_CSV = CACHE_DIR / "daily.csv"
CACHE_META = CACHE_DIR / "metadata.json"
MODEL_DIR = BACKEND_ROOT / "models"
MODEL_PATH = MODEL_DIR / "risk_model.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"
LOO_SCORES_PATH = MODEL_DIR / "loo_scores.json"

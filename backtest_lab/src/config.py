from __future__ import annotations

import os
from pathlib import Path

from server_pipeline.config import (
    ANNUAL_GROWTH_HISTORY_PREFIX,
    QUARTERLY_GROWTH_HISTORY_PREFIX,
    S3_BUCKET,
)


ROOT = Path(__file__).resolve().parents[1]
TMP_DIR = ROOT / "tmp"
RESULT_DIR = TMP_DIR / "results"
DAILY_FEATURE_PATH = TMP_DIR / "daily_features.parquet"
WEEKLY_FEATURE_PATH = TMP_DIR / "weekly_features.parquet"
DEFAULT_START_DATE = os.environ.get("BACKTEST_START_DATE", "2022-01-01")
DEFAULT_END_DATE = os.environ.get("BACKTEST_END_DATE")
WARMUP_CALENDAR_DAYS = int(os.environ.get("BACKTEST_WARMUP_CALENDAR_DAYS", "420"))
ANNUAL_GROWTH_S3_PATH = (
    f"s3://{S3_BUCKET}/{ANNUAL_GROWTH_HISTORY_PREFIX}/"
    "annual_fundamental_growth_history.parquet"
)
QUARTERLY_GROWTH_S3_PATH = (
    f"s3://{S3_BUCKET}/{QUARTERLY_GROWTH_HISTORY_PREFIX}/"
    "quarterly_fundamental_growth_history.parquet"
)

from __future__ import annotations

import os
from pathlib import Path

from backtest_lab.src.config import ANNUAL_GROWTH_S3_PATH, QUARTERLY_GROWTH_S3_PATH


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent
TMP_DIR = ROOT / "tmp"
RESULT_DIR = TMP_DIR / "results"
REPORT_DIR = ROOT / "reports"

DAILY_FEATURE_PATH = Path(
    os.environ.get(
        "CONDITION_BACKTEST_DAILY_FEATURE_PATH",
        TMP_DIR / "daily_features.parquet",
    )
)
WEEKLY_FEATURE_PATH = Path(
    os.environ.get(
        "CONDITION_BACKTEST_WEEKLY_FEATURE_PATH",
        TMP_DIR / "weekly_features.parquet",
    )
)
SP500_BENCHMARK_PATH = Path(
    os.environ.get(
        "CONDITION_BACKTEST_SP500_BENCHMARK_PATH",
        TMP_DIR / "benchmark_sp500_index.parquet",
    )
)

DEFAULT_START_DATE = os.environ.get("CONDITION_BACKTEST_START_DATE", "2020-01-01")
DEFAULT_END_DATE = os.environ.get("CONDITION_BACKTEST_END_DATE")
WARMUP_CALENDAR_DAYS = int(
    os.environ.get("CONDITION_BACKTEST_WARMUP_CALENDAR_DAYS", "420")
)

READ_ONLY_INPUTS = {
    "daily_features": DAILY_FEATURE_PATH,
    "weekly_features": WEEKLY_FEATURE_PATH,
    "sp500_benchmark": SP500_BENCHMARK_PATH,
    "annual_growth": ANNUAL_GROWTH_S3_PATH,
    "quarterly_growth": QUARTERLY_GROWTH_S3_PATH,
}

from __future__ import annotations

from datetime import date

from backtest_lab.src import storage as shared_storage
from condition_backtest_lab.src.config import DAILY_FEATURE_PATH, WEEKLY_FEATURE_PATH


def build_feature_parquets(start_date: date, end_date: date, warmup_days: int) -> None:
    """Build isolated feature files using the existing backtest's proven logic."""
    DAILY_FEATURE_PATH.parent.mkdir(parents=True, exist_ok=True)

    original_daily_path = shared_storage.DAILY_FEATURE_PATH
    original_weekly_path = shared_storage.WEEKLY_FEATURE_PATH
    shared_storage.DAILY_FEATURE_PATH = DAILY_FEATURE_PATH
    shared_storage.WEEKLY_FEATURE_PATH = WEEKLY_FEATURE_PATH
    try:
        shared_storage.build_feature_parquets(start_date, end_date, warmup_days)
    finally:
        shared_storage.DAILY_FEATURE_PATH = original_daily_path
        shared_storage.WEEKLY_FEATURE_PATH = original_weekly_path

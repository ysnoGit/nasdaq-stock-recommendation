from __future__ import annotations

import os
from datetime import date

from server_pipeline.config import RAW_DAILY_PREFIX, S3_BUCKET


BACKTEST_START_DATE = os.environ.get("BACKTEST_START_DATE", "2022-01-01")
BACKTEST_END_DATE = os.environ.get("BACKTEST_END_DATE")
BACKTEST_WARMUP_CALENDAR_DAYS = int(
    os.environ.get("BACKTEST_WARMUP_CALENDAR_DAYS", "420")
)
BACKTEST_SOURCE_S3_LABEL = f"s3://{S3_BUCKET}/{RAW_DAILY_PREFIX}/"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)

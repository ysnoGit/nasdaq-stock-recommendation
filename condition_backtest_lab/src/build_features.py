from __future__ import annotations

import argparse
from datetime import date

from condition_backtest_lab.src.config import (
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    WARMUP_CALENDAR_DAYS,
)
from condition_backtest_lab.src.storage import build_feature_parquets


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build isolated daily and weekly features for condition backtests."
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument(
        "--warmup-calendar-days",
        type=int,
        default=WARMUP_CALENDAR_DAYS,
    )
    args = parser.parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date) or date.today()
    if start_date is None:
        raise RuntimeError("A start date is required.")
    if start_date > end_date:
        raise RuntimeError("Start date must be on or before end date.")

    print("Building condition-backtest feature datasets...")
    build_feature_parquets(start_date, end_date, args.warmup_calendar_days)


if __name__ == "__main__":
    main()

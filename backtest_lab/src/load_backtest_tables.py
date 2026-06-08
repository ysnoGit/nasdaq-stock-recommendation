from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.build_backtest_daily_features import (  # noqa: E402
    build_backtest_daily_features,
    build_backtest_security_master,
)
from backtest_lab.src.build_backtest_weekly_features import build_backtest_weekly_features  # noqa: E402
from backtest_lab.src.config import (  # noqa: E402
    BACKTEST_END_DATE,
    BACKTEST_START_DATE,
    BACKTEST_WARMUP_CALENDAR_DAYS,
    parse_date,
)
from backtest_lab.src.db import (  # noqa: E402
    apply_sql_file,
    connect_supabase,
    delete_date_window,
    require_tables,
    table_count,
    upsert_dataframe,
)


BACKTEST_ROOT = Path(__file__).resolve().parents[1]


MASTER_COLUMNS = [
    "gvkey",
    "iid",
    "ticker",
    "company_name",
    "exchange_code",
    "security_status",
    "security_type",
    "is_active",
    "is_excluded_universe",
    "exclusion_reason",
    "first_seen_date",
    "last_seen_date",
    "source_s3_path",
    "updated_at",
]

DAILY_COLUMNS = [
    "snapshot_date",
    "gvkey",
    "iid",
    "close_price",
    "adjusted_close_price",
    "volume",
    "volume_ma30",
    "volume_ratio",
    "volume_lookback_start_date",
    "volume_lookback_end_date",
    "ma20",
    "ma50",
    "ma100",
    "daily_f_confirmed_using_date",
    "future_daily_ma20",
    "future_daily_ma50",
    "future_daily_ma100",
    "future_daily_close_price",
    "future_daily_adjusted_close_price",
    "source_s3_path",
    "updated_at",
]

WEEKLY_COLUMNS = [
    "week_start_date",
    "week_end_date",
    "gvkey",
    "iid",
    "weekly_open_price",
    "weekly_high_price",
    "weekly_low_price",
    "weekly_close_price",
    "weekly_volume",
    "weekly_ma5",
    "weekly_ma10",
    "weekly_ma30",
    "weekly_h_confirmed_using_date",
    "future_weekly_ma5",
    "future_weekly_ma10",
    "future_weekly_ma30",
    "future_weekly_close_price",
    "source_s3_path",
    "updated_at",
]


def load_table(conn, table: str, df: pd.DataFrame, columns: list[str], conflict_columns: list[str]) -> None:
    before = table_count(conn, table)
    prepared_keys = df[conflict_columns].drop_duplicates().shape[0]
    print(f"\nLoading {table}")
    print(f"Rows prepared: {len(df):,}")
    print(f"Unique keys prepared: {prepared_keys:,}")
    print(f"Rows before load: {before:,}")
    upsert_dataframe(conn, table, df, columns, conflict_columns)
    after = table_count(conn, table)
    print(f"Rows after load: {after:,}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare and load temporary 2022+ backtest feature tables."
    )
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--start-date", default=BACKTEST_START_DATE)
    parser.add_argument("--end-date", default=BACKTEST_END_DATE)
    parser.add_argument("--warmup-calendar-days", type=int, default=BACKTEST_WARMUP_CALENDAR_DAYS)
    args = parser.parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    now = datetime.now(timezone.utc)

    daily = build_backtest_daily_features(
        start_date=start_date,
        end_date=end_date,
        warmup_calendar_days=args.warmup_calendar_days,
    )
    master = build_backtest_security_master(daily)
    weekly = build_backtest_weekly_features(daily)

    master["updated_at"] = now
    daily["updated_at"] = now
    weekly["updated_at"] = now

    daily_start = daily["snapshot_date"].min()
    daily_end = daily["snapshot_date"].max()
    weekly_start = weekly["week_end_date"].min()
    weekly_end = weekly["week_end_date"].max()

    with connect_supabase() as conn:
        if args.apply_schema:
            print("Applying backtest schema...")
            apply_sql_file(conn, BACKTEST_ROOT / "sql" / "create_backtest_tables.sql")

        require_tables(
            conn,
            [
                "backtest_security_master",
                "backtest_daily_feature_snapshot",
                "backtest_weekly_feature_snapshot",
            ],
        )

        with conn.transaction():
            print("\nReplacing backtest feature windows")
            deleted_daily = delete_date_window(
                conn,
                "backtest_daily_feature_snapshot",
                "snapshot_date",
                daily_start,
                daily_end,
            )
            deleted_weekly = delete_date_window(
                conn,
                "backtest_weekly_feature_snapshot",
                "week_end_date",
                weekly_start,
                weekly_end,
            )
            print(f"Deleted backtest daily rows in window: {deleted_daily:,}")
            print(f"Deleted backtest weekly rows in window: {deleted_weekly:,}")

            load_table(conn, "backtest_security_master", master, MASTER_COLUMNS, ["gvkey", "iid"])
            load_table(
                conn,
                "backtest_daily_feature_snapshot",
                daily,
                DAILY_COLUMNS,
                ["snapshot_date", "gvkey", "iid"],
            )
            load_table(
                conn,
                "backtest_weekly_feature_snapshot",
                weekly,
                WEEKLY_COLUMNS,
                ["week_end_date", "gvkey", "iid"],
            )

    print("\nBacktest feature load completed.")


if __name__ == "__main__":
    main()

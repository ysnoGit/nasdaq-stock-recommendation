from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backtest_lab.src.config import DAILY_FEATURE_PATH, WEEKLY_FEATURE_PATH
from server_pipeline.daily.build_daily_market_metrics_s3 import list_raw_objects, parse_raw_files
from server_pipeline.s3_duckdb import connect_duckdb_with_s3
from server_pipeline.utils.trading_calendar import official_week_end_trading_dates


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def select_raw_paths(start_date: date, end_date: date, warmup_days: int) -> list[str]:
    yearly, partitioned = parse_raw_files(list_raw_objects())
    warmup_start = start_date - timedelta(days=warmup_days)
    paths: list[str] = []
    for item in yearly:
        year_start = date(item["year"], 1, 1)
        year_end = date(item["year"], 12, 31)
        if year_end >= warmup_start and year_start <= end_date:
            paths.append(item["path"])
    for item in partitioned:
        if warmup_start <= item["date"] <= end_date:
            paths.append(item["path"])
    paths = sorted(set(paths))
    if not paths:
        raise RuntimeError("No raw daily S3 files selected.")
    return paths


def build_feature_parquets(start_date: date, end_date: date, warmup_days: int) -> None:
    raw_paths = select_raw_paths(start_date, end_date, warmup_days)
    warmup_start = start_date - timedelta(days=warmup_days)
    print(f"Raw S3 files selected: {len(raw_paths):,}")
    print(f"Feature window: {start_date} to {end_date}; warm-up starts {warmup_start}")

    con = connect_duckdb_with_s3()
    daily_query = f"""
    COPY (
        WITH raw_input AS (
            SELECT * FROM read_parquet({raw_paths}, union_by_name = true)
        ),
        clean AS (
            SELECT
                CAST(date AS DATE) AS snapshot_date,
                CAST(gvkey AS VARCHAR) AS gvkey,
                CAST(iid AS VARCHAR) AS iid,
                ticker,
                company_name,
                close_price_raw AS close_price,
                CASE
                    WHEN adjusted_close_price IS NOT NULL THEN adjusted_close_price
                    WHEN adjustment_factor IS NOT NULL AND adjustment_factor <> 0
                    THEN close_price_raw / adjustment_factor
                    ELSE close_price_raw
                END AS adjusted_close_price,
                volume
            FROM raw_input
            WHERE CAST(date AS DATE) BETWEEN DATE '{warmup_start}' AND DATE '{end_date}'
              AND gvkey IS NOT NULL
              AND iid IS NOT NULL
        ),
        dedup AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY snapshot_date, gvkey, iid ORDER BY snapshot_date
                ) AS rn
                FROM clean
                WHERE adjusted_close_price IS NOT NULL AND volume IS NOT NULL
            )
            WHERE rn = 1
        ),
        metrics AS (
            SELECT
                *,
                AVG(adjusted_close_price) OVER (
                    PARTITION BY gvkey, iid ORDER BY snapshot_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS ma20,
                AVG(adjusted_close_price) OVER (
                    PARTITION BY gvkey, iid ORDER BY snapshot_date
                    ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
                ) AS ma50,
                AVG(adjusted_close_price) OVER (
                    PARTITION BY gvkey, iid ORDER BY snapshot_date
                    ROWS BETWEEN 99 PRECEDING AND CURRENT ROW
                ) AS ma100,
                AVG(volume) OVER (
                    PARTITION BY gvkey, iid ORDER BY snapshot_date
                    ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
                ) AS volume_ma30
            FROM dedup
        ),
        future AS (
            SELECT
                *,
                volume / NULLIF(volume_ma30, 0) AS volume_ratio,
                LEAD(snapshot_date) OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS future_daily_confirmation_date,
                LEAD(close_price) OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS future_daily_close_price,
                LEAD(adjusted_close_price) OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS future_daily_adjusted_close_price,
                LEAD(ma20) OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS future_daily_ma20,
                LEAD(ma50) OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS future_daily_ma50,
                LEAD(ma100) OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS future_daily_ma100
            FROM metrics
        )
        SELECT *
        FROM future
        WHERE snapshot_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    ) TO '{sql_path(DAILY_FEATURE_PATH)}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con.execute(daily_query)
    daily_summary = con.execute(
        f"""
        SELECT COUNT(*), MIN(snapshot_date), MAX(snapshot_date), COUNT(DISTINCT (gvkey, iid))
        FROM read_parquet('{sql_path(DAILY_FEATURE_PATH)}')
        """
    ).fetchone()
    print(
        f"Daily feature Parquet: rows={daily_summary[0]:,}, "
        f"dates={daily_summary[1]} to {daily_summary[2]}, securities={daily_summary[3]:,}"
    )

    calendar = official_week_end_trading_dates(start_date, end_date)
    calendar_df = pd.DataFrame(
        [{"week_start_date": week_start, "official_week_end_date": week_end} for week_start, week_end in calendar.items()]
    )
    con.register("calendar_df", calendar_df)
    weekly_query = f"""
    COPY (
        WITH base AS (
            SELECT
                d.*,
                CAST(date_trunc('week', snapshot_date) AS DATE) AS week_start_date
            FROM read_parquet('{sql_path(DAILY_FEATURE_PATH)}') d
        ),
        completed AS (
            SELECT b.*
            FROM base b
            JOIN calendar_df c USING (week_start_date)
            WHERE c.official_week_end_date IN (
                SELECT snapshot_date
                FROM base x
                WHERE x.gvkey = b.gvkey AND x.iid = b.iid
            )
        ),
        bars AS (
            SELECT
                week_start_date,
                MAX(snapshot_date) AS week_end_date,
                gvkey,
                iid,
                arg_min(adjusted_close_price, snapshot_date) AS weekly_open_price,
                MAX(adjusted_close_price) AS weekly_high_price,
                MIN(adjusted_close_price) AS weekly_low_price,
                arg_max(adjusted_close_price, snapshot_date) AS weekly_close_price,
                SUM(volume) AS weekly_volume
            FROM completed
            GROUP BY week_start_date, gvkey, iid
        ),
        moving AS (
            SELECT
                *,
                AVG(weekly_close_price) OVER (
                    PARTITION BY gvkey, iid ORDER BY week_end_date
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) AS weekly_ma5,
                AVG(weekly_close_price) OVER (
                    PARTITION BY gvkey, iid ORDER BY week_end_date
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) AS weekly_ma10,
                AVG(weekly_close_price) OVER (
                    PARTITION BY gvkey, iid ORDER BY week_end_date
                    ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
                ) AS weekly_ma30
            FROM bars
        )
        SELECT
            *,
            LEAD(week_end_date) OVER (PARTITION BY gvkey, iid ORDER BY week_end_date) AS future_weekly_confirmation_date,
            LEAD(weekly_close_price) OVER (PARTITION BY gvkey, iid ORDER BY week_end_date) AS future_weekly_close_price,
            LEAD(weekly_ma5) OVER (PARTITION BY gvkey, iid ORDER BY week_end_date) AS future_weekly_ma5,
            LEAD(weekly_ma10) OVER (PARTITION BY gvkey, iid ORDER BY week_end_date) AS future_weekly_ma10,
            LEAD(weekly_ma30) OVER (PARTITION BY gvkey, iid ORDER BY week_end_date) AS future_weekly_ma30
        FROM moving
    ) TO '{sql_path(WEEKLY_FEATURE_PATH)}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con.execute(weekly_query)
    weekly_summary = con.execute(
        f"""
        SELECT COUNT(*), MIN(week_end_date), MAX(week_end_date), COUNT(DISTINCT (gvkey, iid))
        FROM read_parquet('{sql_path(WEEKLY_FEATURE_PATH)}')
        """
    ).fetchone()
    print(
        f"Weekly feature Parquet: rows={weekly_summary[0]:,}, "
        f"dates={weekly_summary[1]} to {weekly_summary[2]}, securities={weekly_summary[3]:,}"
    )

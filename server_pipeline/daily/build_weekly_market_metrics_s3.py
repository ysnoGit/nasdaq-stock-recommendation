import argparse
import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config import S3_BUCKET, RAW_DAILY_PREFIX, WEEKLY_MARKET_METRICS_PREFIX
from s3_duckdb import connect_duckdb_with_s3


def list_raw_objects() -> list[str]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    keys = []

    for page in paginator.paginate(
        Bucket=S3_BUCKET,
        Prefix=f"{RAW_DAILY_PREFIX}/",
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]

            if key.endswith(".parquet") and "/archive/" not in key:
                keys.append(key)

    return keys


def parse_raw_files(keys: list[str]):
    yearly_files = []
    date_partition_files = []

    yearly_pattern = re.compile(
        r"raw/compustat_daily_security/year=(\d{4})/"
        r"compustat_daily_security_(\d{4})\.parquet$"
    )

    date_pattern = re.compile(
        r"raw/compustat_daily_security/year=(\d{4})/month=(\d{2})/"
        r"date=(\d{4}-\d{2}-\d{2})/"
        r"compustat_daily_security_\d{4}-\d{2}-\d{2}\.parquet$"
    )

    for key in keys:
        yearly_match = yearly_pattern.match(key)
        if yearly_match:
            year = int(yearly_match.group(1))

            # Keep yearly files only for 2020-2025.
            if year <= 2025:
                yearly_files.append(
                    {
                        "key": key,
                        "year": year,
                        "path": f"s3://{S3_BUCKET}/{key}",
                    }
                )
            continue

        date_match = date_pattern.match(key)
        if date_match:
            year = int(date_match.group(1))
            date_str = date_match.group(3)
            trading_date = pd.to_datetime(date_str).date()

            date_partition_files.append(
                {
                    "key": key,
                    "year": year,
                    "date": trading_date,
                    "path": f"s3://{S3_BUCKET}/{key}",
                }
            )

    return yearly_files, date_partition_files


def choose_input_files(
    yearly_files,
    date_partition_files,
    target_weeks: int,
    warmup_calendar_days: int,
):
    if not date_partition_files:
        raise RuntimeError(
            "No date-partitioned raw files found. "
            "This script expects 2026+ raw data to be date-partitioned."
        )

    available_dates = sorted({item["date"] for item in date_partition_files})

    latest_date = available_dates[-1]
    warmup_start_date = latest_date - timedelta(days=warmup_calendar_days)

    selected_paths = []

    # Date-partitioned raw files inside warm-up window.
    for item in date_partition_files:
        if warmup_start_date <= item["date"] <= latest_date:
            selected_paths.append(item["path"])

    # Yearly files if the warm-up window overlaps their year.
    for item in yearly_files:
        year = item["year"]
        year_start = datetime(year, 1, 1).date()
        year_end = datetime(year, 12, 31).date()

        if year_end >= warmup_start_date and year_start <= latest_date:
            selected_paths.append(item["path"])

    selected_paths = sorted(set(selected_paths))

    if not selected_paths:
        raise RuntimeError("No input files selected for weekly processing.")

    return selected_paths, warmup_start_date, latest_date


def upload_df_to_s3_parquet(df: pd.DataFrame, s3_key: str) -> None:
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally build weekly market metrics directly from S3."
    )
    parser.add_argument(
        "--target-weeks",
        type=int,
        default=8,
        help="Number of latest weekly rows to update.",
    )
    parser.add_argument(
        "--warmup-calendar-days",
        type=int,
        default=500,
        help=(
            "Calendar-day lookback used for WMA30. "
            "Needs to be long enough for 30 weekly observations."
        ),
    )

    args = parser.parse_args()

    print("Building incremental weekly market metrics from S3...")
    print(f"Target weeks: {args.target_weeks}")
    print(f"Warm-up calendar days: {args.warmup_calendar_days}")

    keys = list_raw_objects()
    yearly_files, date_partition_files = parse_raw_files(keys)

    raw_paths, warmup_start_date, latest_date = choose_input_files(
        yearly_files=yearly_files,
        date_partition_files=date_partition_files,
        target_weeks=args.target_weeks,
        warmup_calendar_days=args.warmup_calendar_days,
    )

    print("=" * 80)
    print(f"Raw files selected: {len(raw_paths):,}")
    print(f"Warm-up start date: {warmup_start_date}")
    print(f"Latest raw date: {latest_date}")

    print("\nFirst few selected files:")
    for path in raw_paths[:10]:
        print(f"  {path}")

    con = connect_duckdb_with_s3()
    created_at = datetime.now(timezone.utc).isoformat()

    warmup_start_sql = warmup_start_date.strftime("%Y-%m-%d")
    latest_date_sql = latest_date.strftime("%Y-%m-%d")

    query = f"""
    WITH raw_input AS (
        SELECT *
        FROM read_parquet({raw_paths}, union_by_name = true)
    ),

    raw_clean AS (
        SELECT
            CAST(date AS DATE) AS date,
            gvkey,
            iid,
            ticker,
            company_name,
            currency,

            close_price_raw,

            CASE
                WHEN adjusted_close_price IS NOT NULL
                THEN adjusted_close_price
                WHEN adjustment_factor IS NOT NULL
                 AND adjustment_factor != 0
                 AND close_price_raw IS NOT NULL
                THEN close_price_raw / adjustment_factor
                ELSE NULL
            END AS adjusted_close_price

        FROM raw_input
        WHERE CAST(date AS DATE) BETWEEN DATE '{warmup_start_sql}' AND DATE '{latest_date_sql}'
    ),

    base AS (
        SELECT *
        FROM raw_clean
        WHERE adjusted_close_price IS NOT NULL
    ),

    dedup AS (
        SELECT *
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY gvkey, iid, date
                    ORDER BY date DESC
                ) AS rn
            FROM base
        )
        WHERE rn = 1
    ),

    weekly_ranked AS (
        SELECT
            *,
            DATE_TRUNC('week', date) AS week_start_date,
            ROW_NUMBER() OVER (
                PARTITION BY gvkey, iid, DATE_TRUNC('week', date)
                ORDER BY date DESC
            ) AS rn_week
        FROM dedup
    ),

    weekly_close AS (
        SELECT
            gvkey,
            iid,
            ticker,
            company_name,
            currency,
            CAST(week_start_date AS DATE) AS week_start_date,
            date AS week_end_date,

            adjusted_close_price AS weekly_close_price,
            close_price_raw AS weekly_close_price_raw

        FROM weekly_ranked
        WHERE rn_week = 1
    ),

    weekly_ma AS (
        SELECT
            *,
            AVG(weekly_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
            ) AS wma5,

            AVG(weekly_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
            ) AS wma10,

            AVG(weekly_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
                ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
            ) AS wma30
        FROM weekly_close
    ),

    metrics AS (
        SELECT
            *,
            wma5 / NULLIF(wma10, 0) AS wma5_wma10_ratio,
            wma5 / NULLIF(wma30, 0) AS wma5_wma30_ratio,
            wma10 / NULLIF(wma30, 0) AS wma10_wma30_ratio,

            CASE
                WHEN wma5 IS NOT NULL
                 AND wma10 IS NOT NULL
                 AND wma30 IS NOT NULL
                THEN (
                    GREATEST(wma5, wma10, wma30)
                    - LEAST(wma5, wma10, wma30)
                ) / NULLIF((wma5 + wma10 + wma30) / 3, 0)
                ELSE NULL
            END AS weekly_ma_cluster_ratio
        FROM weekly_ma
    ),

    with_previous AS (
        SELECT
            *,
            LAG(wma10) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
            ) AS prev_wma10,

            LAG(wma30) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
            ) AS prev_wma30,

            LAG(wma5_wma10_ratio) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
            ) AS prev_wma5_wma10_ratio,

            LAG(wma5_wma30_ratio) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
            ) AS prev_wma5_wma30_ratio,

            LAG(wma10_wma30_ratio) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
            ) AS prev_wma10_wma30_ratio
        FROM metrics
    ),

    target_weeks AS (
        SELECT DISTINCT week_end_date
        FROM with_previous
        ORDER BY week_end_date DESC
        LIMIT {args.target_weeks}
    ),

    final AS (
        SELECT
            w.week_start_date,
            w.week_end_date,
            w.gvkey,
            w.iid,
            w.ticker,
            w.company_name,
            w.currency,

            w.weekly_close_price,
            w.weekly_close_price_raw,

            w.wma5,
            w.wma10,
            w.wma30,

            w.wma5_wma10_ratio,
            w.wma5_wma30_ratio,
            w.wma10_wma30_ratio,
            w.weekly_ma_cluster_ratio,

            w.prev_wma10,
            w.prev_wma30,
            w.prev_wma5_wma10_ratio,
            w.prev_wma5_wma30_ratio,
            w.prev_wma10_wma30_ratio,

            -- Helper flag only. Backend can recalculate official G dynamically.
            CASE
                WHEN w.wma5_wma10_ratio BETWEEN 0.98 AND 1.02
                 AND w.wma5_wma30_ratio BETWEEN 0.98 AND 1.02
                 AND w.wma10_wma30_ratio BETWEEN 0.98 AND 1.02
                THEN TRUE ELSE FALSE
            END AS flag_g,

            -- Helper flag only. Backend can recalculate official H dynamically.
            CASE
                WHEN w.prev_wma5_wma10_ratio BETWEEN 0.98 AND 1.02
                 AND w.prev_wma5_wma30_ratio BETWEEN 0.98 AND 1.02
                 AND w.prev_wma10_wma30_ratio BETWEEN 0.98 AND 1.02
                 AND w.prev_wma10 <= w.prev_wma30
                 AND w.wma10 > w.wma30
                THEN TRUE ELSE FALSE
            END AS flag_h,

            TIMESTAMP '{created_at}' AS created_at

        FROM with_previous AS w
        INNER JOIN target_weeks AS t
          ON w.week_end_date = t.week_end_date
    )

    SELECT *
    FROM final
    ORDER BY gvkey, iid, week_end_date
    """

    df = con.execute(query).fetchdf()

    print("=" * 80)
    print("Incremental weekly market metrics summary")
    print(f"Output rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Week date range: {df['week_end_date'].min()} to {df['week_end_date'].max()}")
    print(f"Duplicate gvkey-iid-week: {df.duplicated(['gvkey', 'iid', 'week_end_date']).sum():,}")
    print(f"flag_g count: {int(df['flag_g'].sum())}")
    print(f"flag_h count: {int(df['flag_h'].sum())}")

    for week_end_date, week_df in df.groupby("week_end_date"):
        week_str = pd.to_datetime(week_end_date).strftime("%Y-%m-%d")
        year = week_str[:4]

        s3_key = (
            f"{WEEKLY_MARKET_METRICS_PREFIX}/"
            f"year={year}/week_end_date={week_str}/"
            f"weekly_market_metrics_{week_str}.parquet"
        )

        upload_df_to_s3_parquet(week_df, s3_key)

        print(
            f"Uploaded {len(week_df):,} rows to "
            f"s3://{S3_BUCKET}/{s3_key}"
        )

    print("Done.")


if __name__ == "__main__":
    main()

import argparse
import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import S3_BUCKET, RAW_DAILY_PREFIX, DAILY_MARKET_METRICS_PREFIX
from server_pipeline.s3_duckdb import connect_duckdb_with_s3


def list_raw_objects():
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


def parse_raw_files(keys):
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

            # Keep yearly raw files only for 2020-2025.
            # 2026+ should be date-partitioned to avoid duplicate reads.
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


def choose_input_files(yearly_files, date_partition_files, target_days, warmup_calendar_days):
    if not date_partition_files:
        raise RuntimeError(
            "No date-partitioned raw files found. "
            "This incremental processor expects 2026+ raw data to be date-partitioned."
        )

    available_dates = sorted({item["date"] for item in date_partition_files})
    target_dates = available_dates[-target_days:]

    latest_date = target_dates[-1]
    earliest_target_date = target_dates[0]
    warmup_start_date = earliest_target_date - timedelta(days=warmup_calendar_days)

    selected_paths = []

    # Include date-partitioned raw files inside warm-up window.
    for item in date_partition_files:
        if warmup_start_date <= item["date"] <= latest_date:
            selected_paths.append(item["path"])

    # Include yearly files only if the warm-up window overlaps that year.
    # This is mainly needed around early 2026 when MA100 may need late-2025 rows.
    for item in yearly_files:
        year = item["year"]
        year_start = datetime(year, 1, 1).date()
        year_end = datetime(year, 12, 31).date()

        overlaps = year_end >= warmup_start_date and year_start <= latest_date

        if overlaps:
            selected_paths.append(item["path"])

    selected_paths = sorted(set(selected_paths))

    if not selected_paths:
        raise RuntimeError("No input files selected for incremental processing.")

    return selected_paths, target_dates, warmup_start_date, latest_date


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
        description="Incrementally build daily market metrics directly from S3."
    )
    parser.add_argument(
        "--target-days",
        type=int,
        default=5,
        help="Number of latest available trading dates to update.",
    )
    parser.add_argument(
        "--warmup-calendar-days",
        type=int,
        default=250,
        help=(
            "Calendar-day lookback used for rolling metrics. "
            "Needs to be long enough for MA100 and volume_ma30."
        ),
    )

    args = parser.parse_args()

    print("Building incremental daily market metrics from S3...")
    print(f"Target days: {args.target_days}")
    print(f"Warm-up calendar days: {args.warmup_calendar_days}")

    keys = list_raw_objects()
    yearly_files, date_partition_files = parse_raw_files(keys)

    raw_paths, target_dates, warmup_start_date, latest_date = choose_input_files(
        yearly_files=yearly_files,
        date_partition_files=date_partition_files,
        target_days=args.target_days,
        warmup_calendar_days=args.warmup_calendar_days,
    )

    print("=" * 80)
    print(f"Raw files selected: {len(raw_paths):,}")
    print(f"Warm-up start date: {warmup_start_date}")
    print(f"Latest date: {latest_date}")
    print("Target dates:")
    for date_value in target_dates:
        print(f"  {date_value}")

    print("\nFirst few selected files:")
    for path in raw_paths[:10]:
        print(f"  {path}")

    created_at = datetime.now(timezone.utc).isoformat()

    target_date_sql = ", ".join([f"DATE '{d}'" for d in target_dates])
    warmup_start_sql = warmup_start_date.strftime("%Y-%m-%d")
    latest_date_sql = latest_date.strftime("%Y-%m-%d")

    con = connect_duckdb_with_s3()

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
            open_price_raw,
            high_price_raw,
            low_price_raw,
            volume,
            shares_outstanding,
            adjustment_factor,
            total_return_factor,
            exchange_code,
            security_status,
            issue_type_code,

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
          AND volume IS NOT NULL
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

    indicators AS (
        SELECT
            *,
            AVG(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS ma20,

            AVG(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
                ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
            ) AS ma50,

            AVG(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
                ROWS BETWEEN 99 PRECEDING AND CURRENT ROW
            ) AS ma100,

            -- Current day's volume is excluded from volume_ma30.
            AVG(volume) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
                ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
            ) AS volume_ma30
        FROM dedup
    ),

    metrics AS (
        SELECT
            *,
            volume / NULLIF(volume_ma30, 0) AS volume_ratio,

            ma20 / NULLIF(ma50, 0) AS ma20_ma50_ratio,
            ma20 / NULLIF(ma100, 0) AS ma20_ma100_ratio,
            ma50 / NULLIF(ma100, 0) AS ma50_ma100_ratio,

            CASE
                WHEN ma20 IS NOT NULL
                 AND ma50 IS NOT NULL
                 AND ma100 IS NOT NULL
                THEN (
                    GREATEST(ma20, ma50, ma100)
                    - LEAST(ma20, ma50, ma100)
                ) / NULLIF((ma20 + ma50 + ma100) / 3, 0)
                ELSE NULL
            END AS daily_ma_cluster_ratio
        FROM indicators
    ),

    with_previous AS (
        SELECT
            *,
            LAG(ma20) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma20,

            LAG(ma50) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma50,

            LAG(ma100) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma100,

            LAG(ma20_ma50_ratio) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma20_ma50_ratio,

            LAG(ma20_ma100_ratio) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma20_ma100_ratio,

            LAG(ma50_ma100_ratio) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma50_ma100_ratio
        FROM metrics
    ),

    final AS (
        SELECT
            date,
            gvkey,
            iid,
            ticker,
            company_name,
            currency,

            close_price_raw,
            open_price_raw,
            high_price_raw,
            low_price_raw,
            adjusted_close_price,

            volume,
            volume_ma30,
            volume_ratio,

            shares_outstanding,
            adjustment_factor,
            total_return_factor,
            exchange_code,
            security_status,
            issue_type_code,

            ma20,
            ma50,
            ma100,

            ma20_ma50_ratio,
            ma20_ma100_ratio,
            ma50_ma100_ratio,
            daily_ma_cluster_ratio,

            prev_ma20,
            prev_ma50,
            prev_ma100,
            prev_ma20_ma50_ratio,
            prev_ma20_ma100_ratio,
            prev_ma50_ma100_ratio,

            -- Helper flag only. Backend can recalculate official E dynamically.
            CASE
                WHEN ma20_ma50_ratio BETWEEN 0.99 AND 1.01
                 AND ma20_ma100_ratio BETWEEN 0.99 AND 1.01
                 AND ma50_ma100_ratio BETWEEN 0.99 AND 1.01
                THEN TRUE ELSE FALSE
            END AS flag_e,

            -- Deprecated helper flag only. The Supabase serving layer calculates
            -- official F dynamically from future_daily_* values and user tolerance.
            CASE
                WHEN prev_ma20_ma50_ratio BETWEEN 0.99 AND 1.01
                 AND prev_ma20_ma100_ratio BETWEEN 0.99 AND 1.01
                 AND prev_ma50_ma100_ratio BETWEEN 0.99 AND 1.01
                 AND prev_ma20 <= prev_ma50
                 AND ma20 > ma50
                THEN TRUE ELSE FALSE
            END AS flag_f,

            TIMESTAMP '{created_at}' AS created_at

        FROM with_previous
        WHERE date IN ({target_date_sql})
    )

    SELECT *
    FROM final
    ORDER BY gvkey, iid, date
    """

    df = con.execute(query).fetchdf()

    print("=" * 80)
    print("Incremental daily market metrics summary")
    print(f"Output rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Duplicate gvkey-iid-date: {df.duplicated(['gvkey', 'iid', 'date']).sum():,}")
    print(f"flag_e count: {int(df['flag_e'].sum())}")
    print(f"flag_f count: {int(df['flag_f'].sum())}")

    for trading_date, date_df in df.groupby("date"):
        date_str = pd.to_datetime(trading_date).strftime("%Y-%m-%d")
        year = date_str[:4]
        month = date_str[5:7]

        s3_key = (
            f"{DAILY_MARKET_METRICS_PREFIX}/"
            f"year={year}/month={month}/date={date_str}/"
            f"daily_market_metrics_{date_str}.parquet"
        )

        upload_df_to_s3_parquet(date_df, s3_key)

        print(
            f"Uploaded {len(date_df):,} rows to "
            f"s3://{S3_BUCKET}/{s3_key}"
        )

    print("Done.")


if __name__ == "__main__":
    main()

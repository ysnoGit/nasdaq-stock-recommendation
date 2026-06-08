import argparse
import re
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import S3_BUCKET, RAW_DAILY_PREFIX, WEEKLY_MARKET_METRICS_PREFIX
from server_pipeline.s3_duckdb import connect_duckdb_with_s3
from server_pipeline.utils.trading_calendar import (
    official_week_end_trading_date,
    official_week_end_trading_dates,
)


MIN_WEEKLY_COVERAGE_RATIO = 0.9


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


def delete_s3_prefix(s3, prefix: str) -> None:
    print(f"Deleting S3 prefix: s3://{S3_BUCKET}/{prefix}")

    paginator = s3.get_paginator("list_objects_v2")
    keys_to_delete = []

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        keys_to_delete.extend(obj["Key"] for obj in page.get("Contents", []))

    if not keys_to_delete:
        print("  No existing objects found.")
        return

    for index in range(0, len(keys_to_delete), 1000):
        batch = keys_to_delete[index:index + 1000]
        s3.delete_objects(
            Bucket=S3_BUCKET,
            Delete={"Objects": [{"Key": key} for key in batch]},
        )

    print(f"  Deleted {len(keys_to_delete):,} objects.")


def list_legacy_week_end_prefixes(s3) -> list[str]:
    legacy_pattern = re.compile(
        rf"{WEEKLY_MARKET_METRICS_PREFIX}/year=\d{{4}}/"
        r"week_end_date=\d{4}-\d{2}-\d{2}/$"
    )
    paginator = s3.get_paginator("list_objects_v2")
    prefixes = []

    for page in paginator.paginate(
        Bucket=S3_BUCKET,
        Prefix=f"{WEEKLY_MARKET_METRICS_PREFIX}/",
        Delimiter="/",
    ):
        # Top-level common prefixes are year=...; drill into each below.
        for year_item in page.get("CommonPrefixes", []):
            year_prefix = year_item["Prefix"]
            year_pages = paginator.paginate(
                Bucket=S3_BUCKET,
                Prefix=year_prefix,
                Delimiter="/",
            )
            for year_page in year_pages:
                for item in year_page.get("CommonPrefixes", []):
                    prefix = item["Prefix"]
                    if legacy_pattern.match(prefix):
                        prefixes.append(prefix)

    return sorted(set(prefixes))


def cleanup_legacy_week_end_prefixes() -> None:
    s3 = boto3.client("s3")
    legacy_prefixes = list_legacy_week_end_prefixes(s3)

    if not legacy_prefixes:
        print(
            "No legacy week_end_date prefixes found under "
            f"s3://{S3_BUCKET}/{WEEKLY_MARKET_METRICS_PREFIX}/"
        )
        return

    print("Legacy week_end_date prefixes to delete:")
    for prefix in legacy_prefixes:
        print(f"  s3://{S3_BUCKET}/{prefix}")

    for prefix in legacy_prefixes:
        delete_s3_prefix(s3, prefix)

    remaining = list_legacy_week_end_prefixes(s3)
    if remaining:
        raise RuntimeError(
            "Legacy week_end_date cleanup failed. Remaining prefixes:\n"
            + "\n".join(f"s3://{S3_BUCKET}/{prefix}" for prefix in remaining)
        )

    print("Legacy week_end_date cleanup completed.")


def legacy_week_end_prefixes_for_week(s3, week_start_date) -> list[str]:
    week_start = pd.to_datetime(week_start_date).date()
    week_end = week_start + timedelta(days=6)
    candidate_years = sorted({week_start.year, week_end.year})
    legacy_pattern = re.compile(
        rf"{WEEKLY_MARKET_METRICS_PREFIX}/year=\d{{4}}/"
        r"week_end_date=(\d{4}-\d{2}-\d{2})/$"
    )

    legacy_prefixes = []
    for year in candidate_years:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=S3_BUCKET,
            Prefix=f"{WEEKLY_MARKET_METRICS_PREFIX}/year={year}/week_end_date=",
            Delimiter="/",
        ):
            for item in page.get("CommonPrefixes", []):
                prefix = item["Prefix"]
                match = legacy_pattern.match(prefix)
                if not match:
                    continue

                legacy_date = pd.to_datetime(match.group(1)).date()
                legacy_week_start = legacy_date - timedelta(days=legacy_date.weekday())
                if legacy_week_start == week_start:
                    legacy_prefixes.append(prefix)

    return sorted(set(legacy_prefixes))


def validate_weekly_output(df: pd.DataFrame) -> None:
    if df.empty:
        raise RuntimeError("Weekly market metrics output is empty.")

    ticker_week_duplicates = df.duplicated(["ticker", "week_start_date"]).sum()
    if ticker_week_duplicates:
        raise RuntimeError(
            "Weekly validation failed: duplicate ticker-week rows found: "
            f"{ticker_week_duplicates:,}"
        )

    security_week_duplicates = df.duplicated(["gvkey", "iid", "week_start_date"]).sum()
    if security_week_duplicates:
        raise RuntimeError(
            "Weekly validation failed: duplicate gvkey-iid-week rows found: "
            f"{security_week_duplicates:,}"
        )

    week_partition_counts = (
        df.groupby("week_start_date")["week_end_date"]
        .nunique()
        .reset_index(name="week_end_count")
    )
    bad_partitions = week_partition_counts[week_partition_counts["week_end_count"] > 1]
    if not bad_partitions.empty:
        raise RuntimeError(
            "Weekly validation failed: multiple week_end_date values for one "
            f"week_start_date:\n{bad_partitions.to_string(index=False)}"
        )

    week_dates = df[["week_start_date", "week_end_date"]].drop_duplicates()
    bad_official_week_ends = []
    for row in week_dates.itertuples(index=False):
        official_end = official_week_end_trading_date(row.week_start_date)
        row_week_end = pd.Timestamp(row.week_end_date).date()
        if official_end != row_week_end:
            bad_official_week_ends.append(
                {
                    "week_start_date": row.week_start_date,
                    "week_end_date": row_week_end,
                    "official_week_end_date": official_end,
                }
            )
    if bad_official_week_ends:
        bad_df = pd.DataFrame(bad_official_week_ends)
        raise RuntimeError(
            "Weekly validation failed: week_end_date is not the official final "
            "U.S. exchange trading session for the week:\n"
            f"{bad_df.to_string(index=False)}"
        )

    weekly_counts = df.groupby("week_start_date")["ticker"].nunique().sort_index()
    expected_coverage = int(weekly_counts.max() * MIN_WEEKLY_COVERAGE_RATIO)
    low_coverage = weekly_counts[weekly_counts < expected_coverage]

    print("\nWeekly partition validation")
    print(f"Weekly partitions: {len(weekly_counts):,}")
    print(f"Ticker coverage range: {weekly_counts.min():,} to {weekly_counts.max():,}")
    print(f"Coverage warning threshold: {expected_coverage:,}")

    if not low_coverage.empty:
        print("WARNING: completed weekly partitions below expected ticker coverage:")
        for week_start_date, ticker_count in low_coverage.items():
            print(f"  {week_start_date}: {ticker_count:,} tickers")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally build weekly market metrics directly from S3."
    )
    parser.add_argument(
        "--target-weeks",
        type=int,
        default=8,
        help="Number of latest weekly partitions to update when --start-week-date is not set.",
    )
    parser.add_argument(
        "--start-week-date",
        type=str,
        help=(
            "Rebuild every weekly partition from this date's calendar week onward. "
            "Example: 2025-10-10 rebuilds from week_start_date=2025-10-06."
        ),
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
    parser.add_argument(
        "--cleanup-legacy-week-end",
        action="store_true",
        help=(
            "Delete all old week_end_date=... weekly metric prefixes and exit. "
            "The script logs every prefix before deletion."
        ),
    )

    args = parser.parse_args()

    if args.cleanup_legacy_week_end:
        cleanup_legacy_week_end_prefixes()
        return

    print("Building incremental weekly market metrics from S3...")
    start_week_date = None
    if args.start_week_date:
        parsed_start = pd.to_datetime(args.start_week_date).date()
        start_week_date = parsed_start - timedelta(days=parsed_start.weekday())
        print(
            f"Rebuilding weekly partitions from week_start_date={start_week_date} "
            f"(requested {args.start_week_date})"
        )
    else:
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
    official_week_ends = official_week_end_trading_dates(warmup_start_date, latest_date)
    official_week_rows = [
        (week_start, week_end)
        for week_start, week_end in official_week_ends.items()
        if week_end <= latest_date
    ]
    if not official_week_rows:
        raise RuntimeError("No official completed U.S. equity trading weeks found.")

    official_week_values_sql = ",\n        ".join(
        f"(DATE '{week_start}', DATE '{week_end}')"
        for week_start, week_end in sorted(official_week_rows)
    )
    print(f"Official U.S. equity week-end dates available: {len(official_week_rows):,}")

    if start_week_date:
        target_weeks_sql = f"""
        SELECT DISTINCT week_start_date
        FROM with_previous
        WHERE week_start_date >= DATE '{start_week_date}'
        ORDER BY week_start_date DESC
        """
    else:
        target_weeks_sql = f"""
        SELECT DISTINCT week_start_date
        FROM with_previous
        ORDER BY week_start_date DESC
        LIMIT {args.target_weeks}
        """

    query = f"""
    WITH official_week_ends(week_start_date, official_week_end_date) AS (
        VALUES
        {official_week_values_sql}
    ),

    raw_input AS (
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

    market_weeks AS (
        SELECT
            DATE_TRUNC('week', date) AS week_start_date,
            MAX(date) AS market_week_end_date
        FROM dedup
        GROUP BY DATE_TRUNC('week', date)
    ),

    completed_official_weeks AS (
        SELECT
            owe.week_start_date,
            owe.official_week_end_date AS week_end_date
        FROM official_week_ends AS owe
        INNER JOIN market_weeks AS mw
          ON owe.week_start_date = mw.week_start_date
         AND owe.official_week_end_date = mw.market_week_end_date
    ),

    weekly_bars AS (
        SELECT
            w.gvkey,
            w.iid,
            ARG_MAX(w.ticker, w.date) AS ticker,
            ARG_MAX(w.company_name, w.date) AS company_name,
            ARG_MAX(w.currency, w.date) AS currency,
            CAST(w.week_start_date AS DATE) AS week_start_date,
            cow.week_end_date AS week_end_date,
            MAX(w.date) AS security_week_last_trade_date,

            ARG_MIN(w.adjusted_close_price, w.date) AS weekly_open_price,
            MAX(w.adjusted_close_price) AS weekly_high_price,
            MIN(w.adjusted_close_price) AS weekly_low_price,
            ARG_MAX(w.adjusted_close_price, w.date) AS weekly_close_price,
            ARG_MAX(w.close_price_raw, w.date) AS weekly_close_price_raw,
            SUM(w.volume) AS weekly_volume
        FROM weekly_ranked AS w
        INNER JOIN completed_official_weeks AS cow
          ON w.week_start_date = cow.week_start_date
        GROUP BY
            w.gvkey,
            w.iid,
            w.week_start_date,
            cow.week_end_date
    ),

    weekly_ma AS (
        SELECT
            *,
            AVG(weekly_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ) AS wma5,

            AVG(weekly_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ) AS wma10,

            AVG(weekly_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
                ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
            ) AS wma30
        FROM weekly_bars
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
        {target_weeks_sql}
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

            w.weekly_open_price,
            w.weekly_high_price,
            w.weekly_low_price,
            w.weekly_close_price,
            w.weekly_close_price_raw,
            w.weekly_volume,
            w.security_week_last_trade_date,

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

            -- Deprecated helper flag only. The Supabase serving layer calculates
            -- official H dynamically from future_weekly_* values and user tolerance.
            CASE
                WHEN w.prev_wma5_wma10_ratio BETWEEN 0.98 AND 1.02
                 AND w.prev_wma5_wma30_ratio BETWEEN 0.98 AND 1.02
                 AND w.prev_wma10_wma30_ratio BETWEEN 0.98 AND 1.02
                 AND w.prev_wma10 <= w.prev_wma30
                 AND w.wma10 > w.wma30
                THEN TRUE ELSE FALSE
            END AS flag_h,

            DATE '{latest_date_sql}' AS data_as_of_date,
            TIMESTAMP '{created_at}' AS created_at

        FROM with_previous AS w
        INNER JOIN target_weeks AS t
          ON w.week_start_date = t.week_start_date
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
    print(f"Week start range: {df['week_start_date'].min()} to {df['week_start_date'].max()}")
    print(f"Week end range: {df['week_end_date'].min()} to {df['week_end_date'].max()}")
    print(f"Data as of date: {df['data_as_of_date'].max()}")
    print(f"Duplicate ticker-week: {df.duplicated(['ticker', 'week_start_date']).sum():,}")
    print(f"Duplicate gvkey-iid-week: {df.duplicated(['gvkey', 'iid', 'week_start_date']).sum():,}")
    print(f"flag_g count: {int(df['flag_g'].sum())}")
    print(f"flag_h count: {int(df['flag_h'].sum())}")

    validate_weekly_output(df)

    s3 = boto3.client("s3")
    for week_start_date, week_df in df.groupby("week_start_date"):
        week_str = pd.to_datetime(week_start_date).strftime("%Y-%m-%d")
        year = week_str[:4]
        partition_prefix = (
            f"{WEEKLY_MARKET_METRICS_PREFIX}/"
            f"year={year}/week_start_date={week_str}/"
        )

        delete_s3_prefix(s3, partition_prefix)
        for legacy_prefix in legacy_week_end_prefixes_for_week(s3, week_start_date):
            delete_s3_prefix(s3, legacy_prefix)
        remaining_legacy_prefixes = legacy_week_end_prefixes_for_week(s3, week_start_date)
        if remaining_legacy_prefixes:
            raise RuntimeError(
                "Weekly validation failed: old same-week week_end_date prefixes "
                "remain after cleanup:\n"
                + "\n".join(f"s3://{S3_BUCKET}/{prefix}" for prefix in remaining_legacy_prefixes)
            )

        s3_key = (
            f"{partition_prefix}"
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

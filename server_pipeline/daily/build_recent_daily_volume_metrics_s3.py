"""Deprecated recent-volume snapshot builder.

This script is kept for historical/manual inspection only. It is no longer
called by the active EC2 pipeline. In the Supabase serving-layer design,
Condition D is calculated dynamically from three months of
security_feature_snapshot.volume_ratio history.
"""

import argparse
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import (
    S3_BUCKET,
    DAILY_MARKET_METRICS_PREFIX,
    RECENT_DAILY_VOLUME_METRICS_PREFIX,
)
from server_pipeline.s3_duckdb import connect_duckdb_with_s3


def list_daily_metric_paths() -> list[str]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    date_pattern = re.compile(
        rf"{DAILY_MARKET_METRICS_PREFIX}/year=\d{{4}}/month=\d{{2}}/"
        r"date=\d{4}-\d{2}-\d{2}/daily_market_metrics_\d{4}-\d{2}-\d{2}\.parquet$"
    )

    paths = []
    for page in paginator.paginate(
        Bucket=S3_BUCKET,
        Prefix=f"{DAILY_MARKET_METRICS_PREFIX}/",
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if date_pattern.match(key):
                paths.append(f"s3://{S3_BUCKET}/{key}")

    if not paths:
        raise RuntimeError(
            "No date-partitioned daily market metrics found under "
            f"s3://{S3_BUCKET}/{DAILY_MARKET_METRICS_PREFIX}/"
        )

    return sorted(paths)


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
        description="Build recent daily volume metrics from S3 daily metric partitions."
    )
    parser.add_argument(
        "--lookback-months",
        type=int,
        default=3,
        help="Calendar-month lookback from the latest daily metric date.",
    )
    args = parser.parse_args()

    print("Building recent daily volume metrics from S3...")

    input_paths = list_daily_metric_paths()
    print(f"Daily metric partitions found: {len(input_paths):,}")
    print("First few input paths:")
    for path in input_paths[:10]:
        print(f"  {path}")

    created_at = datetime.now(timezone.utc).isoformat()

    con = connect_duckdb_with_s3()

    query = f"""
    WITH max_date AS (
        SELECT MAX(CAST(date AS DATE)) AS latest_date
        FROM read_parquet({input_paths}, union_by_name = true)
    ),

    recent_base AS (
        SELECT
            CAST(d.date AS DATE) AS date,
            d.gvkey,
            d.iid,
            d.ticker,
            d.company_name,
            d.volume,
            d.volume_ma30,
            d.volume_ratio,
            d.adjusted_close_price,
            d.ma20,
            d.ma50,
            d.ma100,
            d.daily_ma_cluster_ratio,
            d.flag_e,
            d.flag_f,
            m.latest_date,
            m.latest_date - INTERVAL '{args.lookback_months} months' AS window_start_date
        FROM read_parquet({input_paths}, union_by_name = true) AS d
        CROSS JOIN max_date AS m
        WHERE CAST(d.date AS DATE) >= m.latest_date - INTERVAL '{args.lookback_months} months'
          AND CAST(d.date AS DATE) <= m.latest_date
          AND d.volume_ratio IS NOT NULL
    )

    SELECT
        *,
        TIMESTAMP '{created_at}' AS created_at
    FROM recent_base
    ORDER BY gvkey, iid, date
    """

    df = con.execute(query).fetchdf()

    print(f"Output rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Latest date: {df['latest_date'].max()}")

    output_key = (
        f"{RECENT_DAILY_VOLUME_METRICS_PREFIX}/"
        "recent_daily_volume_metrics.parquet"
    )

    upload_df_to_s3_parquet(df, output_key)

    print(f"Uploaded to s3://{S3_BUCKET}/{output_key}")
    print("Done.")


if __name__ == "__main__":
    main()

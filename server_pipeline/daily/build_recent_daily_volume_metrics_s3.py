from datetime import datetime, timezone
from io import BytesIO

import boto3
import pandas as pd

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import (
    S3_BUCKET,
    DAILY_MARKET_METRICS_PREFIX,
    RECENT_DAILY_VOLUME_METRICS_PREFIX,
)
from server_pipeline.s3_duckdb import connect_duckdb_with_s3


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
    print("Building recent daily volume metrics from S3...")

    input_path = (
        f"s3://{S3_BUCKET}/"
        f"{DAILY_MARKET_METRICS_PREFIX}/daily_market_metrics.parquet"
    )

    created_at = datetime.now(timezone.utc).isoformat()

    con = connect_duckdb_with_s3()

    query = f"""
    WITH max_date AS (
        SELECT MAX(CAST(date AS DATE)) AS latest_date
        FROM read_parquet('{input_path}')
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
            m.latest_date - INTERVAL '3 months' AS window_start_date
        FROM read_parquet('{input_path}') AS d
        CROSS JOIN max_date AS m
        WHERE CAST(d.date AS DATE) >= m.latest_date - INTERVAL '3 months'
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

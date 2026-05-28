from pathlib import Path
from datetime import datetime, timezone
import os

import boto3
import duckdb
from dotenv import load_dotenv


load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]

DAILY_INDICATORS_PATH = Path(
    "data/processed/daily_market_metrics/daily_market_metrics.parquet"
)

PROCESSED_DIR = Path("data/processed/recent_daily_volume_metrics")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = PROCESSED_DIR / "recent_daily_volume_metrics.parquet"


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def main() -> None:
    if not DAILY_INDICATORS_PATH.exists():
        raise FileNotFoundError(
            f"Daily indicators file not found: {DAILY_INDICATORS_PATH}. "
            "Run build_daily_market_metrics.py first."
        )

    print("Building recent daily volume metrics...")
    print(f"Reading from: {DAILY_INDICATORS_PATH}")

    con = duckdb.connect()

    created_at = datetime.now(timezone.utc).isoformat()

    query = f"""
    WITH max_date AS (
        SELECT MAX(CAST(date AS DATE)) AS latest_date
        FROM read_parquet('{DAILY_INDICATORS_PATH}')
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
            d.flag_e,
            d.flag_f,
            m.latest_date,
            m.latest_date - INTERVAL '3 months' AS window_start_date
        FROM read_parquet('{DAILY_INDICATORS_PATH}') AS d
        CROSS JOIN max_date AS m
        WHERE CAST(d.date AS DATE) >= m.latest_date - INTERVAL '3 months'
          AND CAST(d.date AS DATE) <= m.latest_date
          AND d.volume_ratio IS NOT NULL
    )

    SELECT
        date,
        gvkey,
        iid,
        ticker,
        company_name,
        volume,
        volume_ma30,
        volume_ratio,
        adjusted_close_price,
        ma20,
        ma50,
        ma100,
        flag_e,
        flag_f,
        latest_date,
        window_start_date,
        TIMESTAMP '{created_at}' AS created_at
    FROM recent_base
    ORDER BY gvkey, iid, date
    """

    df = con.execute(query).fetchdf()

    print(f"Output rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Latest date: {df['latest_date'].max()}")
    print(f"Window start date: {df['window_start_date'].min()}")

    df.to_parquet(OUTPUT_FILE, index=False)

    s3_key = (
        "processed/recent_daily_volume_metrics/"
        "recent_daily_volume_metrics.parquet"
    )
    upload_file_to_s3(OUTPUT_FILE, s3_key)

    print("Done.")


if __name__ == "__main__":
    main()

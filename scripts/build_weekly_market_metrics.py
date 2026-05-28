from pathlib import Path
from datetime import datetime, timezone
import os

import boto3
import duckdb
from dotenv import load_dotenv


load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]

DAILY_INDICATORS_PATH = Path("data/processed/daily_market_metrics/daily_market_metrics.parquet")
PROCESSED_DIR = Path("data/processed/weekly_market_metrics")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = PROCESSED_DIR / "weekly_market_metrics.parquet"


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

    print("Building weekly market metrics...")
    print(f"Reading from: {DAILY_INDICATORS_PATH}")

    con = duckdb.connect()

    created_at = datetime.now(timezone.utc).isoformat()

    query = f"""
    WITH daily_base AS (
        SELECT
            CAST(date AS DATE) AS date,
            gvkey,
            iid,
            ticker,
            company_name,
            adjusted_close_price,
            close_price_raw,
            volume,
            currency,

            -- Monday-based week start.
            DATE_TRUNC('week', CAST(date AS DATE)) AS week_start_date
        FROM read_parquet('{DAILY_INDICATORS_PATH}')
        WHERE adjusted_close_price IS NOT NULL
    ),

    weekly_ranked AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY gvkey, iid, week_start_date
                ORDER BY date DESC
            ) AS rn
        FROM daily_base
    ),

    weekly_close AS (
        SELECT
            gvkey,
            iid,
            ticker,
            company_name,
            week_start_date,
            date AS week_end_date,

            -- Last available trading day's adjusted close in the week.
            adjusted_close_price AS weekly_close_price,

            -- Keep raw close for reference.
            close_price_raw AS weekly_close_price_raw,

            currency
        FROM weekly_ranked
        WHERE rn = 1
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

    flag_g_calc AS (
        SELECT
            *,
            CASE
                WHEN wma5 IS NOT NULL
                 AND wma10 IS NOT NULL
                 AND wma30 IS NOT NULL
                 AND (
                    GREATEST(wma5, wma10, wma30)
                    - LEAST(wma5, wma10, wma30)
                 ) / NULLIF((wma5 + wma10 + wma30) / 3, 0) <= 0.02
                THEN TRUE ELSE FALSE
            END AS flag_g
        FROM weekly_ma
    ),

    crossover AS (
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

            LAG(flag_g) OVER (
                PARTITION BY gvkey, iid
                ORDER BY week_end_date
            ) AS prev_flag_g
        FROM flag_g_calc
    )

    SELECT
        *,
        CASE
            WHEN prev_flag_g = TRUE
             AND prev_wma10 <= prev_wma30
             AND wma10 > wma30
            THEN TRUE ELSE FALSE
        END AS flag_h,

        TIMESTAMP '{created_at}' AS created_at

    FROM crossover
    ORDER BY gvkey, iid, week_end_date
    """

    df = con.execute(query).fetchdf()

    print(f"Output rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Date range: {df['week_end_date'].min()} to {df['week_end_date'].max()}")

    df.to_parquet(OUTPUT_FILE, index=False)

    s3_key = "processed/weekly_market_metrics/weekly_market_metrics.parquet"
    upload_file_to_s3(OUTPUT_FILE, s3_key)

    print("Done.")


if __name__ == "__main__":
    main()

from pathlib import Path
from datetime import datetime, timezone
import os

import boto3
import duckdb
from dotenv import load_dotenv


load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]

RAW_BASE_DIR = Path("data/raw/compustat_daily_security")
PROCESSED_DIR = Path("data/processed/daily_market_metrics")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = PROCESSED_DIR / "daily_market_metrics.parquet"


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def find_raw_parquet_files() -> list[str]:
    files = []

    # Keep 2020-2025 yearly files.
    for path in RAW_BASE_DIR.glob("year=*/compustat_daily_security_*.parquet"):
        year_text = path.parent.name.replace("year=", "")
        try:
            year = int(year_text)
        except ValueError:
            continue

        if year <= 2025:
            files.append(str(path))

    # Use 2026+ date-partitioned files.
    for path in RAW_BASE_DIR.glob("year=*/month=*/date=*/*.parquet"):
        files.append(str(path))

    files = sorted(set(files))

    if not files:
        raise FileNotFoundError(
            f"No raw Compustat daily security parquet files found under {RAW_BASE_DIR}"
        )

    return files


def main() -> None:
    raw_files = find_raw_parquet_files()

    print("Building daily market metrics...")
    print(f"Raw files found: {len(raw_files):,}")
    print("First few files:")
    for file in raw_files[:10]:
        print(f"  {file}")

    con = duckdb.connect()
    created_at = datetime.now(timezone.utc).isoformat()

    query = f"""
    WITH raw_input AS (
        SELECT *
        FROM read_parquet({raw_files})
    ),

    base AS (
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

            -- Current day's volume is excluded.
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

    flags AS (
        SELECT
            *,
            CASE
                WHEN daily_ma_cluster_ratio <= 0.01
                THEN TRUE ELSE FALSE
            END AS flag_e,

            LAG(ma20) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma20,

            LAG(ma50) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_ma50,

            LAG(
                CASE
                    WHEN daily_ma_cluster_ratio <= 0.01
                    THEN TRUE ELSE FALSE
                END
            ) OVER (
                PARTITION BY gvkey, iid
                ORDER BY date
            ) AS prev_flag_e
        FROM metrics
    )

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
        shares_outstanding,
        adjustment_factor,
        total_return_factor,
        exchange_code,
        security_status,
        issue_type_code,
        ma20,
        ma50,
        ma100,
        daily_ma_cluster_ratio,
        volume_ma30,
        volume_ratio,
        flag_e,

        CASE
            WHEN prev_flag_e = TRUE
             AND prev_ma20 <= prev_ma50
             AND ma20 > ma50
            THEN TRUE ELSE FALSE
        END AS flag_f,

        TIMESTAMP '{created_at}' AS created_at

    FROM flags
    ORDER BY gvkey, iid, date
    """

    df = con.execute(query).fetchdf()

    print(f"Output rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    df.to_parquet(OUTPUT_FILE, index=False)

    upload_file_to_s3(
        OUTPUT_FILE,
        "processed/daily_market_metrics/daily_market_metrics.parquet",
    )

    print("Done.")


if __name__ == "__main__":
    main()

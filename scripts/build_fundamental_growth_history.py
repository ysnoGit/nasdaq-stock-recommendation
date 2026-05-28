from pathlib import Path
from datetime import datetime, timezone
import os

import boto3
import duckdb
from dotenv import load_dotenv


load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]

ANNUAL_PATH = Path("data/raw/compustat_annual/compustat_annual.parquet")
QUARTERLY_PATH = Path("data/raw/compustat_quarterly/compustat_quarterly.parquet")

ANNUAL_OUT_DIR = Path("data/processed/annual_fundamental_growth_history")
QUARTERLY_OUT_DIR = Path("data/processed/quarterly_fundamental_growth_history")

ANNUAL_OUT_DIR.mkdir(parents=True, exist_ok=True)
QUARTERLY_OUT_DIR.mkdir(parents=True, exist_ok=True)

ANNUAL_OUTPUT_FILE = ANNUAL_OUT_DIR / "annual_fundamental_growth_history.parquet"
QUARTERLY_OUTPUT_FILE = QUARTERLY_OUT_DIR / "quarterly_fundamental_growth_history.parquet"


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def build_annual_growth_history(con: duckdb.DuckDBPyConnection, created_at: str):
    query = f"""
    WITH annual_base AS (
        SELECT
            gvkey,
            CAST(datadate AS DATE) AS datadate,
            fyear,
            ticker,
            company_name,
            currency,
            exchange_code,
            CAST(COALESCE(sale, revt) AS DOUBLE) AS annual_revenue,
            CAST(oiadp AS DOUBLE) AS annual_operating_income
        FROM read_parquet('{ANNUAL_PATH}')
        WHERE gvkey IS NOT NULL
          AND fyear IS NOT NULL
    ),

    annual_dedup AS (
        SELECT *
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY gvkey, fyear
                    ORDER BY datadate DESC
                ) AS rn
            FROM annual_base
        )
        WHERE rn = 1
    ),

    annual_with_lag AS (
        SELECT
            *,
            LAG(annual_revenue) OVER (
                PARTITION BY gvkey
                ORDER BY fyear
            ) AS prev_annual_revenue,

            LAG(annual_operating_income) OVER (
                PARTITION BY gvkey
                ORDER BY fyear
            ) AS prev_annual_operating_income
        FROM annual_dedup
    ),

    annual_growth AS (
        SELECT
            gvkey,
            datadate,
            fyear,
            ticker,
            company_name,
            currency,
            exchange_code,
            annual_revenue,
            annual_operating_income,
            prev_annual_revenue,
            prev_annual_operating_income,

            CASE
                WHEN prev_annual_revenue > 0
                 AND annual_revenue IS NOT NULL
                THEN (annual_revenue - prev_annual_revenue) / prev_annual_revenue
                ELSE NULL
            END AS annual_revenue_growth_yoy,

            CASE
                WHEN prev_annual_operating_income > 0
                 AND annual_operating_income IS NOT NULL
                THEN
                    (annual_operating_income - prev_annual_operating_income)
                    / prev_annual_operating_income
                ELSE NULL
            END AS annual_operating_income_growth_yoy
        FROM annual_with_lag
    )

    SELECT
        *,
        CASE
            WHEN annual_revenue_growth_yoy IS NOT NULL
            THEN TRUE ELSE FALSE
        END AS has_valid_annual_revenue_growth,

        CASE
            WHEN annual_operating_income_growth_yoy IS NOT NULL
            THEN TRUE ELSE FALSE
        END AS has_valid_annual_operating_income_growth,

        CASE
            WHEN annual_revenue_growth_yoy IS NOT NULL
             AND annual_operating_income_growth_yoy IS NOT NULL
            THEN TRUE ELSE FALSE
        END AS has_valid_annual_growth_pair,

        ROW_NUMBER() OVER (
            PARTITION BY gvkey
            ORDER BY fyear DESC, datadate DESC
        ) AS annual_rank_desc,

        TIMESTAMP '{created_at}' AS created_at

    FROM annual_growth
    ORDER BY gvkey, fyear
    """

    return con.execute(query).fetchdf()


def build_quarterly_growth_history(con: duckdb.DuckDBPyConnection, created_at: str):
    query = f"""
    WITH quarterly_base AS (
        SELECT
            gvkey,
            CAST(datadate AS DATE) AS datadate,
            fyearq,
            fqtr,
            ticker,
            company_name,
            currency,
            exchange_code,
            CAST(COALESCE(saleq, revtq) AS DOUBLE) AS quarterly_revenue,
            CAST(oiadpq AS DOUBLE) AS quarterly_operating_income
        FROM read_parquet('{QUARTERLY_PATH}')
        WHERE gvkey IS NOT NULL
          AND fyearq IS NOT NULL
          AND fqtr IS NOT NULL
    ),

    quarterly_dedup AS (
        SELECT *
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY gvkey, fyearq, fqtr
                    ORDER BY datadate DESC
                ) AS rn
            FROM quarterly_base
        )
        WHERE rn = 1
    ),

    quarterly_growth AS (
        SELECT
            cur.gvkey,
            cur.datadate,
            cur.fyearq,
            cur.fqtr,
            cur.ticker,
            cur.company_name,
            cur.currency,
            cur.exchange_code,
            cur.quarterly_revenue,
            cur.quarterly_operating_income,

            prev.quarterly_revenue AS prev_year_same_quarter_revenue,
            prev.quarterly_operating_income AS prev_year_same_quarter_operating_income,

            CASE
                WHEN prev.quarterly_revenue > 0
                 AND cur.quarterly_revenue IS NOT NULL
                THEN
                    (cur.quarterly_revenue - prev.quarterly_revenue)
                    / prev.quarterly_revenue
                ELSE NULL
            END AS quarterly_revenue_growth_yoy,

            CASE
                WHEN prev.quarterly_operating_income > 0
                 AND cur.quarterly_operating_income IS NOT NULL
                THEN
                    (
                        cur.quarterly_operating_income
                        - prev.quarterly_operating_income
                    )
                    / prev.quarterly_operating_income
                ELSE NULL
            END AS quarterly_operating_income_growth_yoy

        FROM quarterly_dedup AS cur
        LEFT JOIN quarterly_dedup AS prev
          ON cur.gvkey = prev.gvkey
         AND cur.fyearq = prev.fyearq + 1
         AND cur.fqtr = prev.fqtr
    )

    SELECT
        *,
        CASE
            WHEN quarterly_revenue_growth_yoy IS NOT NULL
            THEN TRUE ELSE FALSE
        END AS has_valid_quarterly_revenue_growth,

        CASE
            WHEN quarterly_operating_income_growth_yoy IS NOT NULL
            THEN TRUE ELSE FALSE
        END AS has_valid_quarterly_operating_income_growth,

        CASE
            WHEN quarterly_revenue_growth_yoy IS NOT NULL
             AND quarterly_operating_income_growth_yoy IS NOT NULL
            THEN TRUE ELSE FALSE
        END AS has_valid_quarterly_growth_pair,

        ROW_NUMBER() OVER (
            PARTITION BY gvkey
            ORDER BY datadate DESC, fyearq DESC, fqtr DESC
        ) AS quarterly_rank_desc,

        TIMESTAMP '{created_at}' AS created_at

    FROM quarterly_growth
    ORDER BY gvkey, datadate
    """

    return con.execute(query).fetchdf()


def main() -> None:
    if not ANNUAL_PATH.exists():
        raise FileNotFoundError(f"Annual file not found: {ANNUAL_PATH}")

    if not QUARTERLY_PATH.exists():
        raise FileNotFoundError(f"Quarterly file not found: {QUARTERLY_PATH}")

    print("Building fundamental growth history tables...")
    print(f"Annual input: {ANNUAL_PATH}")
    print(f"Quarterly input: {QUARTERLY_PATH}")

    con = duckdb.connect()
    created_at = datetime.now(timezone.utc).isoformat()

    annual_df = build_annual_growth_history(con, created_at)
    quarterly_df = build_quarterly_growth_history(con, created_at)

    print("\nAnnual growth history")
    print(f"Rows: {len(annual_df):,}")
    print(f"Unique GVKEYs: {annual_df['gvkey'].nunique():,}")
    print(f"Fiscal year range: {annual_df['fyear'].min()} to {annual_df['fyear'].max()}")
    print(f"Valid annual growth pair rows: {annual_df['has_valid_annual_growth_pair'].sum():,}")

    print("\nQuarterly growth history")
    print(f"Rows: {len(quarterly_df):,}")
    print(f"Unique GVKEYs: {quarterly_df['gvkey'].nunique():,}")
    print(f"Date range: {quarterly_df['datadate'].min()} to {quarterly_df['datadate'].max()}")
    print(f"Valid quarterly growth pair rows: {quarterly_df['has_valid_quarterly_growth_pair'].sum():,}")

    annual_df.to_parquet(ANNUAL_OUTPUT_FILE, index=False)
    quarterly_df.to_parquet(QUARTERLY_OUTPUT_FILE, index=False)

    upload_file_to_s3(
        ANNUAL_OUTPUT_FILE,
        "processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet",
    )

    upload_file_to_s3(
        QUARTERLY_OUTPUT_FILE,
        "processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet",
    )

    print("Done.")


if __name__ == "__main__":
    main()

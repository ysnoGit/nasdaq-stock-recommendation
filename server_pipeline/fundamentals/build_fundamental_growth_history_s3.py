from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import (
    S3_BUCKET,
    RAW_ANNUAL_PREFIX,
    RAW_QUARTERLY_PREFIX,
    ANNUAL_GROWTH_HISTORY_PREFIX,
    QUARTERLY_GROWTH_HISTORY_PREFIX,
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


def build_annual_growth_history(con, annual_input_path: str, created_at: str) -> pd.DataFrame:
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
        FROM read_parquet('{annual_input_path}', union_by_name = true)
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


def build_quarterly_growth_history(con, quarterly_input_path: str, created_at: str) -> pd.DataFrame:
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
        FROM read_parquet('{quarterly_input_path}', union_by_name = true)
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
    print("Building fundamental growth history directly from S3...")

    annual_input_path = (
        f"s3://{S3_BUCKET}/{RAW_ANNUAL_PREFIX}/latest/compustat_annual.parquet"
    )
    quarterly_input_path = (
        f"s3://{S3_BUCKET}/{RAW_QUARTERLY_PREFIX}/latest/compustat_quarterly.parquet"
    )

    print(f"Annual input: {annual_input_path}")
    print(f"Quarterly input: {quarterly_input_path}")

    con = connect_duckdb_with_s3()
    created_at = datetime.now(timezone.utc).isoformat()

    annual_df = build_annual_growth_history(con, annual_input_path, created_at)
    quarterly_df = build_quarterly_growth_history(con, quarterly_input_path, created_at)

    print("\nAnnual growth history")
    print(f"Rows: {len(annual_df):,}")
    print(f"Unique GVKEYs: {annual_df['gvkey'].nunique():,}")
    print(f"Fiscal year range: {annual_df['fyear'].min()} to {annual_df['fyear'].max()}")
    print(f"Valid annual growth pair rows: {annual_df['has_valid_annual_growth_pair'].sum():,}")
    print(
        "Duplicate gvkey-fyear:",
        f"{annual_df.duplicated(['gvkey', 'fyear']).sum():,}",
    )

    print("\nQuarterly growth history")
    print(f"Rows: {len(quarterly_df):,}")
    print(f"Unique GVKEYs: {quarterly_df['gvkey'].nunique():,}")
    print(f"Date range: {quarterly_df['datadate'].min()} to {quarterly_df['datadate'].max()}")
    print(f"Valid quarterly growth pair rows: {quarterly_df['has_valid_quarterly_growth_pair'].sum():,}")
    print(
        "Duplicate gvkey-fyearq-fqtr:",
        f"{quarterly_df.duplicated(['gvkey', 'fyearq', 'fqtr']).sum():,}",
    )

    annual_output_key = (
        f"{ANNUAL_GROWTH_HISTORY_PREFIX}/annual_fundamental_growth_history.parquet"
    )
    quarterly_output_key = (
        f"{QUARTERLY_GROWTH_HISTORY_PREFIX}/quarterly_fundamental_growth_history.parquet"
    )

    upload_df_to_s3_parquet(annual_df, annual_output_key)
    upload_df_to_s3_parquet(quarterly_df, quarterly_output_key)

    print(f"\nUploaded annual growth history to s3://{S3_BUCKET}/{annual_output_key}")
    print(f"Uploaded quarterly growth history to s3://{S3_BUCKET}/{quarterly_output_key}")
    print("Done.")


if __name__ == "__main__":
    main()

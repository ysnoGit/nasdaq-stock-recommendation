import argparse
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys
from typing import Any

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import (
    S3_BUCKET,
    RAW_ANNUAL_PREFIX,
    RAW_QUARTERLY_PREFIX,
)
from server_pipeline.utils.wrds_connection import get_wrds_connection


def upload_df_to_s3_parquet(df: pd.DataFrame, s3_key: str) -> None:
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue(),
    )


def validate_annual(df: pd.DataFrame) -> None:
    print("\nAnnual fundamentals validation")
    print(f"Rows: {len(df):,}")
    print(f"Unique GVKEYs: {df['gvkey'].nunique():,}")
    print(f"Fiscal year range: {df['fyear'].min()} to {df['fyear'].max()}")
    print(f"Datadate range: {df['datadate'].min()} to {df['datadate'].max()}")
    print(f"Missing sale: {df['sale'].isna().sum():,}")
    print(f"Missing revt: {df['revt'].isna().sum():,}")
    print(f"Missing oiadp: {df['oiadp'].isna().sum():,}")
    print(f"Duplicate gvkey-fyear rows: {df.duplicated(['gvkey', 'fyear']).sum():,}")


def validate_quarterly(df: pd.DataFrame) -> None:
    print("\nQuarterly fundamentals validation")
    print(f"Rows: {len(df):,}")
    print(f"Unique GVKEYs: {df['gvkey'].nunique():,}")
    print(f"Fiscal year range: {df['fyearq'].min()} to {df['fyearq'].max()}")
    print(f"Datadate range: {df['datadate'].min()} to {df['datadate'].max()}")
    print(f"Missing saleq: {df['saleq'].isna().sum():,}")
    print(f"Missing revtq: {df['revtq'].isna().sum():,}")
    print(f"Missing oiadpq: {df['oiadpq'].isna().sum():,}")
    print(
        "Duplicate gvkey-fyearq-fqtr rows:",
        f"{df.duplicated(['gvkey', 'fyearq', 'fqtr']).sum():,}",
    )


def download_annual(conn: Any, annual_start_year: int) -> pd.DataFrame:
    query = f"""
        select
            gvkey,
            datadate,
            fyear,
            fyr,
            indfmt,
            consol,
            popsrc,
            datafmt,
            tic as ticker,
            conm as company_name,
            cusip,
            cik,
            costat,
            fic,
            curcd as currency,
            exchg as exchange_code,
            sale,
            revt,
            oiadp,
            at,
            csho,
            prcc_f,
            mkvalt
        from comp.funda
        where fyear >= {annual_start_year}
          and indfmt = 'INDL'
          and consol = 'C'
          and popsrc = 'D'
          and datafmt = 'STD'
          and gvkey in (
              select distinct gvkey
              from comp.secd
              where exchg = 14
                and secstat = 'A'
                and tpci = '0'
          )
    """

    print("=" * 80)
    print("Downloading Compustat annual fundamentals from WRDS...")
    df = conn.raw_sql(query, date_cols=["datadate"])
    validate_annual(df)
    return df


def download_quarterly(conn: Any, quarterly_start_date: str) -> pd.DataFrame:
    query = f"""
        select
            gvkey,
            datadate,
            fyearq,
            fqtr,
            fyr,
            indfmt,
            consol,
            popsrc,
            datafmt,
            tic as ticker,
            conm as company_name,
            cusip,
            cik,
            costat,
            fic,
            curcdq as currency,
            exchg as exchange_code,
            saleq,
            revtq,
            oiadpq,
            atq,
            cshoq,
            prccq,
            mkvaltq
        from comp.fundq
        where datadate >= '{quarterly_start_date}'
          and indfmt = 'INDL'
          and consol = 'C'
          and popsrc = 'D'
          and datafmt = 'STD'
          and gvkey in (
              select distinct gvkey
              from comp.secd
              where exchg = 14
                and secstat = 'A'
                and tpci = '0'
          )
    """

    print("=" * 80)
    print("Downloading Compustat quarterly fundamentals from WRDS...")
    df = conn.raw_sql(query, date_cols=["datadate"])
    validate_quarterly(df)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Compustat annual and quarterly fundamentals directly to S3."
    )
    parser.add_argument(
        "--annual-start-year",
        type=int,
        default=2017,
        help="Earliest fiscal year for annual fundamentals.",
    )
    parser.add_argument(
        "--quarterly-start-date",
        type=str,
        default="2019-01-01",
        help="Earliest datadate for quarterly fundamentals.",
    )

    args = parser.parse_args()

    extract_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Connecting to WRDS...")
    conn = get_wrds_connection()

    try:
        annual_df = download_annual(conn, args.annual_start_year)
        quarterly_df = download_quarterly(conn, args.quarterly_start_date)
    finally:
        conn.close()
        print("WRDS connection closed.")

    # Store versioned raw files.
    annual_versioned_key = (
        f"{RAW_ANNUAL_PREFIX}/extract_date={extract_date}/compustat_annual.parquet"
    )
    quarterly_versioned_key = (
        f"{RAW_QUARTERLY_PREFIX}/extract_date={extract_date}/compustat_quarterly.parquet"
    )

    # Store stable latest raw files for processing.
    annual_latest_key = f"{RAW_ANNUAL_PREFIX}/latest/compustat_annual.parquet"
    quarterly_latest_key = f"{RAW_QUARTERLY_PREFIX}/latest/compustat_quarterly.parquet"

    for key in [annual_versioned_key, annual_latest_key]:
        upload_df_to_s3_parquet(annual_df, key)
        print(f"Uploaded annual fundamentals to s3://{S3_BUCKET}/{key}")

    for key in [quarterly_versioned_key, quarterly_latest_key]:
        upload_df_to_s3_parquet(quarterly_df, key)
        print(f"Uploaded quarterly fundamentals to s3://{S3_BUCKET}/{key}")

    print("Done.")


if __name__ == "__main__":
    main()

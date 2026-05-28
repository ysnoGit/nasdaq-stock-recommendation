import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import wrds
from dotenv import load_dotenv


load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

# Longer than strictly necessary, so we can calculate historical YoY growth safely.
ANNUAL_START_YEAR = 2017
QUARTERLY_START_DATE = "2019-01-01"

EXTRACT_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

LOCAL_ANNUAL_DIR = Path("data/raw/compustat_annual")
LOCAL_QUARTERLY_DIR = Path("data/raw/compustat_quarterly")

LOCAL_ANNUAL_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_QUARTERLY_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def validate_annual(df) -> None:
    print("\nAnnual fundamentals validation")
    print(f"Rows: {len(df):,}")
    print(f"Unique GVKEYs: {df['gvkey'].nunique():,}")
    print(f"Fiscal year range: {df['fyear'].min()} to {df['fyear'].max()}")
    print(f"Datadate range: {df['datadate'].min()} to {df['datadate'].max()}")
    print(f"Missing sale: {df['sale'].isna().sum():,}")
    print(f"Missing revt: {df['revt'].isna().sum():,}")
    print(f"Missing oiadp: {df['oiadp'].isna().sum():,}")

    dup_count = df.duplicated(subset=["gvkey", "fyear"]).sum()
    if dup_count > 0:
        print(f"WARNING: Duplicate gvkey-fyear rows: {dup_count:,}")


def validate_quarterly(df) -> None:
    print("\nQuarterly fundamentals validation")
    print(f"Rows: {len(df):,}")
    print(f"Unique GVKEYs: {df['gvkey'].nunique():,}")
    print(f"Fiscal year range: {df['fyearq'].min()} to {df['fyearq'].max()}")
    print(f"Datadate range: {df['datadate'].min()} to {df['datadate'].max()}")
    print(f"Missing saleq: {df['saleq'].isna().sum():,}")
    print(f"Missing revtq: {df['revtq'].isna().sum():,}")
    print(f"Missing oiadpq: {df['oiadpq'].isna().sum():,}")

    dup_count = df.duplicated(subset=["gvkey", "fyearq", "fqtr"]).sum()
    if dup_count > 0:
        print(f"WARNING: Duplicate gvkey-fyearq-fqtr rows: {dup_count:,}")


def download_annual(conn: wrds.Connection) -> None:
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
        where fyear >= {ANNUAL_START_YEAR}
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
    print("Downloading Compustat annual fundamentals...")
    df = conn.raw_sql(query, date_cols=["datadate"])

    validate_annual(df)

    local_path = LOCAL_ANNUAL_DIR / "compustat_annual.parquet"
    df.to_parquet(local_path, index=False)

    s3_key = (
        f"raw/compustat_annual/extract_date={EXTRACT_DATE}/"
        "compustat_annual.parquet"
    )
    upload_file_to_s3(local_path, s3_key)


def download_quarterly(conn: wrds.Connection) -> None:
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
        where datadate >= '{QUARTERLY_START_DATE}'
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
    print("Downloading Compustat quarterly fundamentals...")
    df = conn.raw_sql(query, date_cols=["datadate"])

    validate_quarterly(df)

    local_path = LOCAL_QUARTERLY_DIR / "compustat_quarterly.parquet"
    df.to_parquet(local_path, index=False)

    s3_key = (
        f"raw/compustat_quarterly/extract_date={EXTRACT_DATE}/"
        "compustat_quarterly.parquet"
    )
    upload_file_to_s3(local_path, s3_key)


def main() -> None:
    print("Connecting to WRDS...")
    conn = wrds.Connection(wrds_username=WRDS_USERNAME)

    try:
        download_annual(conn)
        download_quarterly(conn)
    finally:
        conn.close()
        print("WRDS connection closed.")


if __name__ == "__main__":
    main()

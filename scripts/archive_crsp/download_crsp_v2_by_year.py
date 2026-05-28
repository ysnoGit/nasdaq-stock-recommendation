import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import wrds
from dotenv import load_dotenv


load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

START_YEAR = 2025
END_YEAR = datetime.now(timezone.utc).year

LOCAL_BASE_DIR = Path("data/raw/crsp_daily")
LOCAL_BASE_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def validate_crsp_v2_year(df, year: int) -> None:
    if df.empty:
        print(f"WARNING: CRSP v2 data for {year} is empty.")
        return

    print(f"Validation for {year}")
    print(f"Rows: {len(df):,}")
    print(f"Unique PERMNOs: {df['permno'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    invalid_exchange = df[df["primaryexch"] != "Q"]
    if not invalid_exchange.empty:
        raise ValueError(f"Found non-NASDAQ rows in year {year}")

    duplicate_count = df.duplicated(subset=["permno", "date"]).sum()
    if duplicate_count > 0:
        print(f"WARNING: Found {duplicate_count:,} duplicate permno-date rows in year {year}")

    print("Primary exchange values:", sorted(df["primaryexch"].dropna().unique()))
    print("Share type values:", sorted(df["sharetype"].dropna().unique()))
    print("Security type values:", sorted(df["securitytype"].dropna().unique()))
    print("Security subtype values:", sorted(df["securitysubtype"].dropna().unique()))


def download_crsp_v2_year(conn: wrds.Connection, year: int) -> None:
    start_date = f"{year}-01-01"
    current_year = datetime.now(timezone.utc).year

    if year == current_year:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        end_date = f"{year}-12-31"

    query = f"""
        select
            permno,
            permco,
            dlycaldt as date,
            dlyprc as prc,
            dlyvol as vol,
            dlyret as ret,
            shrout,
            dlycumfacpr as cfacpr,
            dlycumfacshr as cfacshr,
            dlyopen as openprc,
            dlynumtrd as numtrd,
            ticker,
            primaryexch,
            sharetype,
            securitytype,
            securitysubtype,
            issuertype,
            conditionaltype,
            tradingstatusflg,
            siccd,
            cusip
        from crsp.dsf_v2
        where dlycaldt between '{start_date}' and '{end_date}'
          and primaryexch = 'Q'
          and sharetype = 'NS'
          and securitytype = 'EQTY'
          and securitysubtype = 'COM'
    """

    print("=" * 80)
    print(f"Downloading CRSP v2 daily stock data for {year}")
    print(f"Date range: {start_date} to {end_date}")

    df = conn.raw_sql(query, date_cols=["date"])

    validate_crsp_v2_year(df, year)

    local_dir = LOCAL_BASE_DIR / f"year={year}"
    local_dir.mkdir(parents=True, exist_ok=True)

    local_path = local_dir / f"crsp_daily_{year}.parquet"
    df.to_parquet(local_path, index=False)

    s3_key = f"raw/crsp_daily/year={year}/crsp_daily_{year}.parquet"
    upload_file_to_s3(local_path, s3_key)

    print(f"Completed CRSP v2 year {year}")
    print("=" * 80)


def main() -> None:
    print("Connecting to WRDS...")
    conn = wrds.Connection(wrds_username=WRDS_USERNAME)

    try:
        for year in range(START_YEAR, END_YEAR + 1):
            download_crsp_v2_year(conn, year)
    finally:
        conn.close()
        print("WRDS connection closed.")


if __name__ == "__main__":
    main()

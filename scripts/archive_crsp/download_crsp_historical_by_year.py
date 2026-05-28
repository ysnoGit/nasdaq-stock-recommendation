import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import wrds
from dotenv import load_dotenv


load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

# Change this range when needed
START_YEAR = 2020
END_YEAR = datetime.now(timezone.utc).year

LOCAL_BASE_DIR = Path("data/raw/crsp_daily")
LOCAL_BASE_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")

    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")

    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def validate_crsp_year(df, year: int) -> None:
    if df.empty:
        print(f"WARNING: CRSP data for {year} is empty.")
        return

    print(f"Validation for {year}")
    print(f"Rows: {len(df):,}")
    print(f"Unique PERMNOs: {df['permno'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    invalid_exchcd = df[df["exchcd"] != 3]
    invalid_shrcd = df[~df["shrcd"].isin([10, 11])]

    if not invalid_exchcd.empty:
        raise ValueError(f"Found non-NASDAQ rows in year {year}")

    if not invalid_shrcd.empty:
        raise ValueError(f"Found non-common-share rows in year {year}")

    duplicate_count = df.duplicated(subset=["permno", "date"]).sum()

    if duplicate_count > 0:
        print(f"WARNING: Found {duplicate_count:,} duplicate permno-date rows in year {year}")


def download_crsp_year(conn: wrds.Connection, year: int) -> None:
    start_date = f"{year}-01-01"
    current_year = datetime.now(timezone.utc).year

    if year == current_year:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        end_date = f"{year}-12-31"

    query = f"""
        select
            dsf.permno,
            dsf.permco,
            dsf.date,
            dsf.prc,
            dsf.vol,
            dsf.ret,
            dsf.shrout,
            dsf.cfacpr,
            dsf.cfacshr,
            dsf.openprc,
            dsf.numtrd,
            sn.ticker,
            sn.comnam,
            sn.exchcd,
            sn.shrcd,
            sn.siccd,
            sn.cusip
        from crsp.dsf as dsf
        join crsp.stocknames as sn
          on dsf.permno = sn.permno
         and dsf.date between sn.namedt and sn.nameenddt
        where dsf.date between '{start_date}' and '{end_date}'
          and sn.exchcd = 3
          and sn.shrcd in (10, 11)
    """

    print("=" * 80)
    print(f"Downloading CRSP daily stock data for {year}")
    print(f"Date range: {start_date} to {end_date}")

    df = conn.raw_sql(query, date_cols=["date"])

    validate_crsp_year(df, year)

    local_dir = LOCAL_BASE_DIR / f"year={year}"
    local_dir.mkdir(parents=True, exist_ok=True)

    local_path = local_dir / f"crsp_daily_{year}.parquet"
    df.to_parquet(local_path, index=False)

    s3_key = f"raw/crsp_daily/year={year}/crsp_daily_{year}.parquet"
    upload_file_to_s3(local_path, s3_key)

    print(f"Completed year {year}")
    print("=" * 80)


def main() -> None:
    print("Connecting to WRDS...")
    conn = wrds.Connection(wrds_username=WRDS_USERNAME)

    try:
        for year in range(START_YEAR, END_YEAR + 1):
            download_crsp_year(conn, year)
    finally:
        conn.close()
        print("WRDS connection closed.")


if __name__ == "__main__":
    main()

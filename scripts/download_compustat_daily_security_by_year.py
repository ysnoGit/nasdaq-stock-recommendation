import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import wrds
from dotenv import load_dotenv


load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

# For testing, set both to 2026.
# For full extraction, change START_YEAR to 2020.
START_YEAR = 2020
END_YEAR = datetime.now(timezone.utc).year

LOCAL_BASE_DIR = Path("data/raw/compustat_daily_security")
LOCAL_BASE_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def validate_compustat_daily_year(df, year: int) -> None:
    if df.empty:
        print(f"WARNING: Compustat daily security data for {year} is empty.")
        return

    print(f"Validation for {year}")
    print(f"Rows: {len(df):,}")
    print(f"Unique GVKEYs: {df['gvkey'].nunique():,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    if not df[df["exchange_code"] != 14].empty:
        raise ValueError(f"Found non-NASDAQ rows in year {year}")

    if not df[df["security_status"] != "A"].empty:
        raise ValueError(f"Found non-active security rows in year {year}")

    if not df[df["issue_type_code"] != "0"].empty:
        raise ValueError(f"Found non-common-stock issue rows in year {year}")

    duplicate_count = df.duplicated(subset=["gvkey", "iid", "date"]).sum()
    if duplicate_count > 0:
        print(
            f"WARNING: Found {duplicate_count:,} duplicate "
            f"gvkey-iid-date rows in year {year}"
        )

    missing_close = df["close_price_raw"].isna().sum()
    missing_volume = df["volume"].isna().sum()

    if missing_close > 0:
        print(f"WARNING: Missing close price rows: {missing_close:,}")

    if missing_volume > 0:
        print(f"WARNING: Missing volume rows: {missing_volume:,}")


def download_compustat_daily_year(conn: wrds.Connection, year: int) -> None:
    start_date = f"{year}-01-01"
    current_year = datetime.now(timezone.utc).year

    if year == current_year:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    else:
        end_date = f"{year}-12-31"

    query = f"""
        select
            datadate as date,
            gvkey,
            iid,
            tic as ticker,
            conm as company_name,
            cusip,
            cik,
            exchg as exchange_code,
            secstat as security_status,
            tpci as issue_type_code,
            prccd as close_price_raw,
            prcod as open_price_raw,
            prchd as high_price_raw,
            prcld as low_price_raw,
            cshtrd as volume,
            cshoc as shares_outstanding,
            ajexdi as adjustment_factor,
            trfd as total_return_factor,
            curcdd as currency,
            fic
        from comp.secd
        where datadate between '{start_date}' and '{end_date}'
          and exchg = 14
          and secstat = 'A'
          and tpci = '0'
          and prccd is not null
          and cshtrd is not null
    """

    print("=" * 80)
    print(f"Downloading Compustat daily security data for {year}")
    print(f"Date range: {start_date} to {end_date}")

    df = conn.raw_sql(query, date_cols=["date"])

    if not df.empty:
        df["adjustment_factor"] = df["adjustment_factor"].fillna(1.0)
        df["adjusted_close_price"] = (
            df["close_price_raw"] / df["adjustment_factor"]
        )
        df["data_source"] = "compustat_daily_security"
        df["created_at"] = datetime.now(timezone.utc)

    validate_compustat_daily_year(df, year)

    local_dir = LOCAL_BASE_DIR / f"year={year}"
    local_dir.mkdir(parents=True, exist_ok=True)

    local_path = local_dir / f"compustat_daily_security_{year}.parquet"
    df.to_parquet(local_path, index=False)

    s3_key = (
        f"raw/compustat_daily_security/year={year}/"
        f"compustat_daily_security_{year}.parquet"
    )

    upload_file_to_s3(local_path, s3_key)

    print(f"Completed year {year}")
    print("=" * 80)


def main() -> None:
    print("Connecting to WRDS...")
    conn = wrds.Connection(wrds_username=WRDS_USERNAME)

    try:
        for year in range(START_YEAR, END_YEAR + 1):
            download_compustat_daily_year(conn, year)
    finally:
        conn.close()
        print("WRDS connection closed.")


if __name__ == "__main__":
    main()

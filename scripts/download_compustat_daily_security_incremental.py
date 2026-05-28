import argparse
import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import wrds
from dotenv import load_dotenv


load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

LOCAL_BASE_DIR = Path("data/raw/compustat_daily_security")
LOCAL_BASE_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    boto3.client("s3").upload_file(str(local_path), S3_BUCKET, s3_key)


def get_latest_trading_dates(conn: wrds.Connection, lookback_days: int) -> list[str]:
    query = f"""
        select distinct datadate
        from comp.secd
        where exchg = 14
          and secstat = 'A'
          and tpci = '0'
          and prccd is not null
          and cshtrd is not null
        order by datadate desc
        limit {lookback_days}
    """

    df = conn.raw_sql(query, date_cols=["datadate"])

    dates = (
        df["datadate"]
        .dt.strftime("%Y-%m-%d")
        .sort_values()
        .tolist()
    )

    return dates


def download_one_date(conn: wrds.Connection, date_str: str) -> None:
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
        where datadate = '{date_str}'
          and exchg = 14
          and secstat = 'A'
          and tpci = '0'
          and prccd is not null
          and cshtrd is not null
    """

    print("=" * 80)
    print(f"Downloading Compustat daily security data for {date_str}")

    df = conn.raw_sql(query, date_cols=["date"])

    if df.empty:
        print(f"WARNING: no rows for {date_str}")
        return

    df["adjustment_factor"] = df["adjustment_factor"].fillna(1.0)
    df["adjusted_close_price"] = (
        df["close_price_raw"] / df["adjustment_factor"]
    )
    df["data_source"] = "compustat_daily_security"
    df["created_at"] = datetime.now(timezone.utc)

    year = date_str[:4]
    month = date_str[5:7]

    local_dir = (
        LOCAL_BASE_DIR
        / f"year={year}"
        / f"month={month}"
        / f"date={date_str}"
    )
    local_dir.mkdir(parents=True, exist_ok=True)

    local_path = local_dir / f"compustat_daily_security_{date_str}.parquet"
    df.to_parquet(local_path, index=False)

    s3_key = (
        f"raw/compustat_daily_security/"
        f"year={year}/month={month}/date={date_str}/"
        f"compustat_daily_security_{date_str}.parquet"
    )

    upload_file_to_s3(local_path, s3_key)

    print(f"Rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Uploaded to s3://{S3_BUCKET}/{s3_key}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download latest Compustat daily security rows as date partitions."
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=10,
        help="Number of latest available trading dates to re-download.",
    )

    args = parser.parse_args()

    print("Connecting to WRDS...")
    conn = wrds.Connection(wrds_username=WRDS_USERNAME)

    try:
        dates = get_latest_trading_dates(conn, args.lookback_days)

        print(f"Latest {args.lookback_days} available trading dates:")
        for date_str in dates:
            print(f"  {date_str}")

        for date_str in dates:
            download_one_date(conn, date_str)

    finally:
        conn.close()
        print("WRDS connection closed.")


if __name__ == "__main__":
    main()

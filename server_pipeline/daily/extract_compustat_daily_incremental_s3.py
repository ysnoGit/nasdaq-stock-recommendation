import argparse
from datetime import datetime, timezone
from io import BytesIO

import boto3
import pandas as pd
import wrds

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config import S3_BUCKET, WRDS_USERNAME, RAW_DAILY_PREFIX


def upload_df_to_s3_parquet(df: pd.DataFrame, s3_key: str) -> None:
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue(),
    )


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

    return (
        df["datadate"]
        .dt.strftime("%Y-%m-%d")
        .sort_values()
        .tolist()
    )


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
    df["adjusted_close_price"] = df["close_price_raw"] / df["adjustment_factor"]
    df["data_source"] = "compustat_daily_security"
    df["created_at"] = datetime.now(timezone.utc)

    year = date_str[:4]
    month = date_str[5:7]

    s3_key = (
        f"{RAW_DAILY_PREFIX}/"
        f"year={year}/month={month}/date={date_str}/"
        f"compustat_daily_security_{date_str}.parquet"
    )

    upload_df_to_s3_parquet(df, s3_key)

    print(f"Rows: {len(df):,}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Uploaded to s3://{S3_BUCKET}/{s3_key}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download latest Compustat daily security rows directly to S3."
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

import os
import re
from pathlib import Path

import boto3
import pandas as pd
import wrds
from dotenv import load_dotenv


load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

RAW_LOCAL_DIR = Path("data/raw/compustat_daily_security")
DAILY_MARKET_METRICS_PATH = Path(
    "data/processed/daily_market_metrics/daily_market_metrics.parquet"
)


def get_wrds_latest_date():
    print("Checking latest date from WRDS comp.secd...")

    conn = wrds.Connection(wrds_username=WRDS_USERNAME)

    try:
        df = conn.raw_sql("""
            select
                max(datadate) as latest_wrds_date
            from comp.secd
            where exchg = 14
              and secstat = 'A'
              and tpci = '0'
              and prccd is not null
              and cshtrd is not null
        """, date_cols=["latest_wrds_date"])

        latest_date = df.loc[0, "latest_wrds_date"]

        count_df = conn.raw_sql(f"""
            select
                count(*) as row_count,
                count(distinct gvkey) as unique_gvkeys,
                count(distinct tic) as unique_tickers
            from comp.secd
            where datadate = '{latest_date.strftime("%Y-%m-%d")}'
              and exchg = 14
              and secstat = 'A'
              and tpci = '0'
              and prccd is not null
              and cshtrd is not null
        """)

        return latest_date.date(), count_df

    finally:
        conn.close()


def get_local_raw_latest_date():
    dates = []

    for path in RAW_LOCAL_DIR.glob("year=*/month=*/date=*/*.parquet"):
        match = re.search(r"date=(\d{4}-\d{2}-\d{2})", str(path))
        if match:
            dates.append(pd.to_datetime(match.group(1)).date())

    if not dates:
        return None

    return max(dates)


def get_s3_raw_latest_date():
    s3 = boto3.client("s3")
    prefix = "raw/compustat_daily_security/"

    dates = []
    continuation_token = None

    while True:
        kwargs = {
            "Bucket": S3_BUCKET,
            "Prefix": prefix,
        }

        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token

        response = s3.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            key = obj["Key"]
            match = re.search(r"date=(\d{4}-\d{2}-\d{2})", key)
            if match:
                dates.append(pd.to_datetime(match.group(1)).date())

        if response.get("IsTruncated"):
            continuation_token = response.get("NextContinuationToken")
        else:
            break

    if not dates:
        return None

    return max(dates)


def get_processed_latest_date():
    if not DAILY_MARKET_METRICS_PATH.exists():
        return None

    df = pd.read_parquet(
        DAILY_MARKET_METRICS_PATH,
        columns=["date"],
    )

    return pd.to_datetime(df["date"]).dt.date.max()


def main():
    wrds_latest_date, wrds_count_df = get_wrds_latest_date()
    local_raw_latest_date = get_local_raw_latest_date()
    s3_raw_latest_date = get_s3_raw_latest_date()
    processed_latest_date = get_processed_latest_date()

    print("\n" + "=" * 80)
    print("Compustat Daily Update Status")
    print("=" * 80)

    print(f"WRDS latest available date:        {wrds_latest_date}")
    print(f"Local raw latest date:             {local_raw_latest_date}")
    print(f"S3 raw latest date:                {s3_raw_latest_date}")
    print(f"Processed daily metrics latest:    {processed_latest_date}")

    print("\nWRDS latest-date row count:")
    print(wrds_count_df.to_string(index=False))

    print("\nStatus check:")

    if local_raw_latest_date == wrds_latest_date:
        print("✅ Local raw data is up to date with WRDS.")
    else:
        print("⚠️ Local raw data is NOT up to date with WRDS.")

    if s3_raw_latest_date == wrds_latest_date:
        print("✅ S3 raw data is up to date with WRDS.")
    else:
        print("⚠️ S3 raw data is NOT up to date with WRDS.")

    if processed_latest_date == wrds_latest_date:
        print("✅ Processed daily market metrics are up to date with WRDS.")
    else:
        print("⚠️ Processed daily market metrics are NOT up to date with WRDS.")

    print("\nRecommended action:")

    if s3_raw_latest_date != wrds_latest_date or local_raw_latest_date != wrds_latest_date:
        print("Run:")
        print("python3 scripts/download_compustat_daily_security_incremental.py --lookback-days 10")

    if processed_latest_date != wrds_latest_date:
        print("Then rebuild processed layers:")
        print("python3 scripts/build_daily_market_metrics.py")
        print("python3 scripts/build_recent_daily_volume_metrics.py")
        print("python3 scripts/build_weekly_market_metrics.py")


if __name__ == "__main__":
    main()

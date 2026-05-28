from pathlib import Path
import os

import boto3
import pandas as pd
from dotenv import load_dotenv


load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]

INPUT_FILE = Path(
    "data/raw/compustat_daily_security/year=2026/"
    "compustat_daily_security_2026.parquet"
)

OUTPUT_BASE_DIR = Path("data/raw/compustat_daily_security")


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    boto3.client("s3").upload_file(str(local_path), S3_BUCKET, s3_key)


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    print(f"Reading: {INPUT_FILE}")
    df = pd.read_parquet(INPUT_FILE)

    df["date"] = pd.to_datetime(df["date"]).dt.date

    print(f"Rows: {len(df):,}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"Unique dates: {df['date'].nunique():,}")

    for trading_date, date_df in df.groupby("date"):
        date_str = trading_date.strftime("%Y-%m-%d")
        year = trading_date.strftime("%Y")
        month = trading_date.strftime("%m")

        local_dir = (
            OUTPUT_BASE_DIR
            / f"year={year}"
            / f"month={month}"
            / f"date={date_str}"
        )
        local_dir.mkdir(parents=True, exist_ok=True)

        local_path = local_dir / f"compustat_daily_security_{date_str}.parquet"
        date_df.to_parquet(local_path, index=False)

        s3_key = (
            f"raw/compustat_daily_security/"
            f"year={year}/month={month}/date={date_str}/"
            f"compustat_daily_security_{date_str}.parquet"
        )

        upload_file_to_s3(local_path, s3_key)
        print(f"Uploaded {date_str}: {len(date_df):,} rows")

    print("Done converting 2026 yearly file into date partitions.")


if __name__ == "__main__":
    main()

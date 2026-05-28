import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import wrds
from dotenv import load_dotenv

load_dotenv()

WRDS_USERNAME = os.environ["WRDS_USERNAME"]
S3_BUCKET = os.environ["S3_BUCKET"]

EXTRACT_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
LOCAL_DIR = Path("data/raw/crsp_daily")
LOCAL_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = "2024-01-02"
END_DATE = "2024-01-10"

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=WRDS_USERNAME)

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
    where dsf.date between '{START_DATE}' and '{END_DATE}'
      and sn.exchcd = 3
      and sn.shrcd in (10, 11)
"""

print("Downloading CRSP sample...")
df = conn.raw_sql(query, date_cols=["date"])
conn.close()

print(f"Downloaded rows: {len(df):,}")
print(df.head())

local_path = LOCAL_DIR / f"crsp_daily_sample_{START_DATE}_{END_DATE}.parquet"
df.to_parquet(local_path, index=False)

s3_key = (
    f"raw/crsp_daily/extract_date={EXTRACT_DATE}/"
    f"crsp_daily_sample_{START_DATE}_{END_DATE}.parquet"
)

print(f"Uploading to s3://{S3_BUCKET}/{s3_key}")
boto3.client("s3").upload_file(str(local_path), S3_BUCKET, s3_key)

print("Done.")

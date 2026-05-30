import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=username)

print("Connected successfully.")

df = conn.raw_sql("""
    select
        max(datadate) as latest_date,
        count(*) as row_count
    from comp.secd
    where exchg = 14
      and secstat = 'A'
      and tpci = '0'
      and prccd is not null
      and cshtrd is not null
""", date_cols=["latest_date"])

print(df)

conn.close()
print("Connection closed.")

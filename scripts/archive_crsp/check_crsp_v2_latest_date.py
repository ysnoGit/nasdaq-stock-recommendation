import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=username)

df = conn.raw_sql("""
    select
        min(dlycaldt) as min_date,
        max(dlycaldt) as max_date,
        count(*) as row_count
    from crsp.dsf_v2
""")

print(df)

conn.close()
print("Connection closed.")

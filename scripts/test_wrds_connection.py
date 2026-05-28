import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=username)

df = conn.raw_sql("""
    select permno, date, prc, vol
    from crsp.dsf
    where date = '2024-01-02'
    limit 10
""")

print(df)

conn.close()
print("Connection closed.")

import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=username)

df = conn.raw_sql("""
    select
        exchg,
        count(*) as row_count,
        count(distinct gvkey) as company_count
    from comp.secd
    where datadate between '2026-05-01' and '2026-05-24'
    group by exchg
    order by row_count desc
""")

print(df)

conn.close()
print("Connection closed.")

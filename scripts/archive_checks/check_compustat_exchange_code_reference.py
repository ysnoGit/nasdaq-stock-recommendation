import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=username)

print("\nColumns in comp.r_ex_codes:")
desc = conn.describe_table(library="comp", table="r_ex_codes")
print(desc[["name", "type", "comment"]].to_string(index=False))

print("\nExchange code reference data:")
df = conn.raw_sql("""
    select *
    from comp.r_ex_codes
    order by 1
""")

print(df.to_string(index=False))

conn.close()
print("Connection closed.")

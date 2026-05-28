import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

conn = wrds.Connection(wrds_username=username)

for table in ["funda", "fundq"]:
    print("=" * 100)
    print(f"TABLE: comp.{table}")

    desc = conn.describe_table(library="comp", table=table)
    print(desc[["name", "type", "comment"]].to_string(index=False))

    date_col = "datadate"

    result = conn.raw_sql(f"""
        select
            min({date_col}) as min_date,
            max({date_col}) as max_date,
            count(*) as row_count
        from comp.{table}
    """)

    print("\nDate coverage:")
    print(result)

conn.close()

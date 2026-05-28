import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

conn = wrds.Connection(wrds_username=username)

candidate_tables = [
    "dsf",
    "dsf_v2",
    "stocknames",
    "stocknames_v2",
    "stkdlysecuritydata",
    "stkdlysecurityprimarydata",
    "stksecurityinfohist",
    "stksecurityinfohdr",
]

for table in candidate_tables:
    print("=" * 100)
    print(f"TABLE: crsp.{table}")

    try:
        desc = conn.describe_table(library="crsp", table=table)
        print(desc[["name", "type", "comment"]].to_string(index=False))

        if "date" in desc["name"].tolist():
            date_col = "date"
        elif "datadate" in desc["name"].tolist():
            date_col = "datadate"
        elif "dlycaldt" in desc["name"].tolist():
            date_col = "dlycaldt"
        else:
            date_col = None

        if date_col:
            q = f"""
                select min({date_col}) as min_date,
                       max({date_col}) as max_date,
                       count(*) as row_count
                from crsp.{table}
            """
            result = conn.raw_sql(q)
            print("\nDate coverage:")
            print(result)
        else:
            print("\nNo obvious date column found for min/max check.")

    except Exception as e:
        print(f"ERROR inspecting crsp.{table}: {e}")

conn.close()

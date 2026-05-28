import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username=username)

df = conn.raw_sql("""
    select
        datadate,
        gvkey,
        iid,
        tic,
        conm,
        exchg,
        secstat,
        tpci,
        prccd,
        prcod,
        prchd,
        prcld,
        cshtrd,
        ajexdi,
        curcdd
    from comp.secd
    where datadate between '2026-05-01' and '2026-05-24'
      and exchg = 14
      and prccd is not null
      and cshtrd is not null
    order by datadate, tic
    limit 100
""", date_cols=["datadate"])

print(df.to_string(index=False))

print("\nsecstat values:")
print(df["secstat"].value_counts(dropna=False))

print("\ntpci values:")
print(df["tpci"].value_counts(dropna=False))

conn.close()
print("Connection closed.")

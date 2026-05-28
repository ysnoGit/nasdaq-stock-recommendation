import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

conn = wrds.Connection(wrds_username=username)

print("\nAvailable libraries containing 'crsp':")
libs = conn.list_libraries()
for lib in libs:
    if "crsp" in lib.lower():
        print(lib)

print("\nTables in crsp library containing daily/dsf/stock/security:")
tables = conn.list_tables(library="crsp")
for table in tables:
    t = table.lower()
    if any(keyword in t for keyword in ["dsf", "daily", "stock", "security", "ciz", "dly"]):
        print(table)

conn.close()

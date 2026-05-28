import os
import wrds
from dotenv import load_dotenv

load_dotenv()

username = os.environ["WRDS_USERNAME"]

conn = wrds.Connection(wrds_username=username)

print("\nColumns in crsp.dsf:")
print(conn.describe_table(library="crsp", table="dsf"))

print("\nColumns in crsp.stocknames:")
print(conn.describe_table(library="crsp", table="stocknames"))

conn.close()

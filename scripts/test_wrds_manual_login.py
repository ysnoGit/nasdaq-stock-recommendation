import wrds

print("Connecting to WRDS...")
conn = wrds.Connection(wrds_username="ysno")

df = conn.raw_sql("select current_date as today")
print(df)

conn.close()
print("Connection closed.")

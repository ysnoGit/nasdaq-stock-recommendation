import duckdb
import boto3

from server_pipeline.config import AWS_REGION


def connect_duckdb_with_s3() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()

    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")

    session = boto3.Session(region_name=AWS_REGION)
    credentials = session.get_credentials()

    if credentials is None:
        raise RuntimeError(
            "AWS credentials not found. Run `aws configure` or check your AWS setup."
        )

    frozen = credentials.get_frozen_credentials()

    con.execute(f"SET s3_region='{AWS_REGION}';")
    con.execute(f"SET s3_access_key_id='{frozen.access_key}';")
    con.execute(f"SET s3_secret_access_key='{frozen.secret_key}';")

    if frozen.token:
        con.execute(f"SET s3_session_token='{frozen.token}';")

    return con

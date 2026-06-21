from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
import re
import sys
from typing import Any

import boto3
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import (  # noqa: E402
    S3_BUCKET,
    ANNUAL_GROWTH_HISTORY_PREFIX,
    DAILY_MARKET_METRICS_PREFIX,
    QUARTERLY_GROWTH_HISTORY_PREFIX,
    WEEKLY_MARKET_METRICS_PREFIX,
)
from server_pipeline.utils.trading_calendar import (  # noqa: E402
    official_week_end_trading_date,
    official_trading_sessions,
    week_start_for_date,
)
from server_pipeline.utils.universe_filter import add_universe_filter_columns  # noqa: E402


ANNUAL_GROWTH_S3_PATH = (
    f"s3://{S3_BUCKET}/{ANNUAL_GROWTH_HISTORY_PREFIX}/"
    "annual_fundamental_growth_history.parquet"
)
QUARTERLY_GROWTH_S3_PATH = (
    f"s3://{S3_BUCKET}/{QUARTERLY_GROWTH_HISTORY_PREFIX}/"
    "quarterly_fundamental_growth_history.parquet"
)

DEFAULT_SERVING_HISTORY_START_DATE = date(2024, 6, 3)
DEFAULT_INSPECTION_TRADING_DAYS = 15
DEFAULT_WEEKLY_LOOKBACK_WEEKS = 36
UPSERT_BATCH_SIZE = 5_000


def require_supabase_db_url() -> str:
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Run:\n"
            'export SUPABASE_DB_URL="postgresql://..."'
        )
    return db_url


def connect_supabase():
    db_url = require_supabase_db_url()
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is not installed. Run: python3 -m pip install 'psycopg[binary]'"
        ) from exc

    return psycopg.connect(db_url)


def s3_client():
    return boto3.client("s3")


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected S3 URI, got: {uri}")
    bucket, key = uri[5:].split("/", 1)
    return bucket, key


def read_s3_parquet(uri: str) -> pd.DataFrame:
    bucket, key = parse_s3_uri(uri)
    response = s3_client().get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(BytesIO(response["Body"].read()))


def list_partitioned_paths(prefix: str, pattern: re.Pattern[str]) -> list[dict[str, Any]]:
    s3 = s3_client()
    paginator = s3.get_paginator("list_objects_v2")
    items = []

    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"{prefix}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            match = pattern.match(key)
            if match:
                items.append(
                    {
                        "key": key,
                        "path": f"s3://{S3_BUCKET}/{key}",
                        **match.groupdict(),
                    }
                )

    return sorted(items, key=lambda item: item["key"])


def list_daily_metric_paths() -> list[dict[str, Any]]:
    pattern = re.compile(
        rf"{DAILY_MARKET_METRICS_PREFIX}/year=(?P<year>\d{{4}})/month=(?P<month>\d{{2}})/"
        r"date=(?P<date>\d{4}-\d{2}-\d{2})/"
        r"daily_market_metrics_\d{4}-\d{2}-\d{2}\.parquet$"
    )
    return list_partitioned_paths(DAILY_MARKET_METRICS_PREFIX, pattern)


def list_weekly_metric_paths() -> list[dict[str, Any]]:
    pattern = re.compile(
        rf"{WEEKLY_MARKET_METRICS_PREFIX}/year=(?P<year>\d{{4}})/"
        r"week_start_date=(?P<week_start_date>\d{4}-\d{2}-\d{2})/"
        r"weekly_market_metrics_\d{4}-\d{2}-\d{2}\.parquet$"
    )
    return list_partitioned_paths(WEEKLY_MARKET_METRICS_PREFIX, pattern)


def read_many_parquet(paths: list[dict[str, Any]]) -> pd.DataFrame:
    frames = []
    for item in paths:
        df = read_s3_parquet(item["path"])
        df["source_s3_path"] = item["path"]
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def normalize_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def normalize_records(df: pd.DataFrame) -> list[tuple[Any, ...]]:
    normalized = df.astype(object).where(pd.notna(df), None)
    records = []
    for row in normalized.itertuples(index=False, name=None):
        records.append(tuple(normalize_value(value) for value in row))
    return records


def apply_schema(conn) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "create_supabase_serving_tables.sql"
    with schema_path.open("r", encoding="utf-8") as handle:
        sql_text = handle.read()

    with conn.cursor() as cur:
        cur.execute(sql_text)


def recreate_serving_schema(conn) -> None:
    recreate_path = (
        Path(__file__).resolve().parents[2]
        / "sql"
        / "recreate_supabase_serving_tables.sql"
    )
    with recreate_path.open("r", encoding="utf-8") as handle:
        drop_sql = handle.read()

    print("Dropping production serving tables only; backtest tables are untouched...")
    with conn.cursor() as cur:
        cur.execute(drop_sql)
    apply_schema(conn)


def table_count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])


def table_exists(conn, table: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table,))
        return cur.fetchone()[0] is not None


def require_tables(conn, tables: list[str]) -> None:
    missing = [table for table in tables if not table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "Missing Supabase serving table(s): "
            f"{', '.join(missing)}. Run:\n"
            "bash scripts/load_processed_features_to_supabase.sh --apply-schema"
        )


def required_tables_for_load(only: str | None) -> list[str]:
    if only == "security":
        return [
            "security_master",
            "security_daily_feature_snapshot",
            "security_weekly_feature_snapshot",
        ]
    if only == "security-master":
        return ["security_master"]
    if only == "company-master":
        return ["company_master"]
    if only == "daily":
        return ["security_daily_feature_snapshot"]
    if only == "weekly":
        return ["security_weekly_feature_snapshot"]
    if only == "annual":
        return ["annual_growth_history"]
    if only == "quarterly":
        return ["quarterly_growth_history"]
    return [
        "security_master",
        "company_master",
        "security_daily_feature_snapshot",
        "security_weekly_feature_snapshot",
        "annual_growth_history",
        "quarterly_growth_history",
    ]


def deactivate_security_master(conn) -> None:
    require_tables(conn, ["security_master"])
    with conn.cursor() as cur:
        cur.execute("UPDATE security_master SET is_active = false, updated_at = now()")


def upsert_dataframe(
    conn,
    table: str,
    df: pd.DataFrame,
    columns: list[str],
    conflict_columns: list[str],
) -> None:
    if df.empty:
        raise RuntimeError(f"No rows to load into {table}.")

    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns for {table}: {missing}")

    insert_columns = ", ".join(columns)
    conflict_target = ", ".join(conflict_columns)
    update_columns = [
        column
        for column in columns
        if column not in conflict_columns and column != "created_at"
    ]
    update_clause = ", ".join(
        f"{column} = EXCLUDED.{column}"
        for column in update_columns
    )

    staging_table = f"serving_load_{table}"
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {staging_table}")
        cur.execute(
            f"CREATE TEMP TABLE {staging_table} "
            f"(LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP"
        )
        copy_sql = f"COPY {staging_table} ({insert_columns}) FROM STDIN"
        copied_rows = 0
        for offset in range(0, len(df), UPSERT_BATCH_SIZE):
            batch = df.iloc[offset : offset + UPSERT_BATCH_SIZE]
            with cur.copy(copy_sql) as copy:
                for record in normalize_records(batch[columns]):
                    copy.write_row(record)
            copied_rows += len(batch)
            print(
                f"Staged {table}: {copied_rows:,}/{len(df):,} rows"
            )
        cur.execute(
            f"""
            INSERT INTO {table} ({insert_columns})
            SELECT {insert_columns}
            FROM {staging_table}
            WHERE true
            ON CONFLICT ({conflict_target})
            DO UPDATE SET {update_clause}
            """
        )
        print(f"Merged staged rows into {table}: {cur.rowcount:,}")


def copy_dataframe(
    conn,
    table: str,
    df: pd.DataFrame,
    columns: list[str],
) -> None:
    if df.empty:
        raise RuntimeError(f"No rows to load into {table}.")

    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns for {table}: {missing}")

    insert_columns = ", ".join(columns)
    copy_sql = f"COPY {table} ({insert_columns}) FROM STDIN"
    copied_rows = 0
    next_progress = 100_000
    with conn.cursor() as cur:
        with cur.copy(copy_sql) as copy:
            for offset in range(0, len(df), UPSERT_BATCH_SIZE):
                batch = df.iloc[offset : offset + UPSERT_BATCH_SIZE]
                for record in normalize_records(batch[columns]):
                    copy.write_row(record)
                copied_rows += len(batch)
                if copied_rows >= next_progress or copied_rows == len(df):
                    print(f"Copied {table}: {copied_rows:,}/{len(df):,} rows")
                    next_progress += 100_000


def daily_history_window(
    paths: list[dict[str, Any]],
    history_start_date: date,
) -> list[dict[str, Any]]:
    if not paths:
        raise RuntimeError(
            f"No daily metric partitions found under s3://{S3_BUCKET}/{DAILY_MARKET_METRICS_PREFIX}/"
        )

    for item in paths:
        item["date_value"] = pd.to_datetime(item["date"]).date()

    latest_date = max(item["date_value"] for item in paths)
    selected = [
        item
        for item in paths
        if history_start_date <= item["date_value"] <= latest_date
    ]

    if not selected:
        raise RuntimeError(
            "No daily metric partitions selected for "
            f"security_daily_feature_snapshot on or after {history_start_date}."
        )

    print(f"Daily metric latest date: {latest_date}")
    print(f"Daily serving history start: {history_start_date}")
    print(f"Daily metric partitions selected: {len(selected):,}")
    return selected


def rolling_daily_history_start(
    latest_daily_date: date,
    lookback_months: int,
    inspection_trading_days: int,
) -> tuple[date, date]:
    calendar_days = max(60, inspection_trading_days * 3)
    sessions = official_trading_sessions(
        latest_daily_date - timedelta(days=calendar_days),
        latest_daily_date,
    )
    if len(sessions) < inspection_trading_days:
        raise RuntimeError(
            f"Only {len(sessions)} official sessions are available; "
            f"cannot prepare {inspection_trading_days} inspection trading days."
        )
    inspection_start_date = sessions[-inspection_trading_days]
    history_start_date = (
        pd.Timestamp(inspection_start_date) - pd.DateOffset(months=lookback_months)
    ).date()
    return history_start_date, inspection_start_date


def build_annual_rows() -> pd.DataFrame:
    df = read_s3_parquet(ANNUAL_GROWTH_S3_PATH)
    print(f"Annual growth input rows: {len(df):,}")
    print(f"Annual growth columns: {list(df.columns)}")

    required = [
        "gvkey",
        "fyear",
        "datadate",
        "annual_rank_desc",
        "annual_revenue",
        "annual_operating_income",
        "annual_revenue_growth_yoy",
        "annual_operating_income_growth_yoy",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise RuntimeError(f"Annual growth parquet missing expected columns: {missing}")

    now = datetime.now(timezone.utc)
    out = pd.DataFrame(
        {
            "gvkey": df["gvkey"].astype(str),
            "fyear": df["fyear"].astype("Int64"),
            "datadate": pd.to_datetime(df["datadate"]).dt.date,
            "annual_rank_desc": df["annual_rank_desc"].astype("Int64"),
            "annual_revenue": df["annual_revenue"],
            "annual_operating_income": df["annual_operating_income"],
            "annual_revenue_growth": df["annual_revenue_growth_yoy"],
            "annual_operating_income_growth": df["annual_operating_income_growth_yoy"],
            # The processed feature file does not carry its raw extract_date.
            "source_extract_date": None,
            "source_s3_path": ANNUAL_GROWTH_S3_PATH,
            "updated_at": now,
        }
    )
    return out


def build_quarterly_rows() -> pd.DataFrame:
    df = read_s3_parquet(QUARTERLY_GROWTH_S3_PATH)
    print(f"Quarterly growth input rows: {len(df):,}")
    print(f"Quarterly growth columns: {list(df.columns)}")

    required = [
        "gvkey",
        "fyearq",
        "fqtr",
        "datadate",
        "quarterly_rank_desc",
        "quarterly_revenue",
        "quarterly_operating_income",
        "quarterly_revenue_growth_yoy",
        "quarterly_operating_income_growth_yoy",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise RuntimeError(f"Quarterly growth parquet missing expected columns: {missing}")

    now = datetime.now(timezone.utc)
    out = pd.DataFrame(
        {
            "gvkey": df["gvkey"].astype(str),
            "fyearq": df["fyearq"].astype("Int64"),
            "fqtr": df["fqtr"].astype("Int64"),
            "datadate": pd.to_datetime(df["datadate"]).dt.date,
            "quarterly_rank_desc": df["quarterly_rank_desc"].astype("Int64"),
            "quarterly_revenue": df["quarterly_revenue"],
            "quarterly_operating_income": df["quarterly_operating_income"],
            "quarterly_revenue_growth": df["quarterly_revenue_growth_yoy"],
            "quarterly_operating_income_growth": df["quarterly_operating_income_growth_yoy"],
            # The processed feature file does not carry its raw extract_date.
            "source_extract_date": None,
            "source_s3_path": QUARTERLY_GROWTH_S3_PATH,
            "updated_at": now,
        }
    )
    return out


def build_company_master_rows() -> pd.DataFrame:
    annual = read_s3_parquet(ANNUAL_GROWTH_S3_PATH)
    quarterly = read_s3_parquet(QUARTERLY_GROWTH_S3_PATH)
    required = ["gvkey", "datadate", "ticker", "company_name", "exchange_code"]
    for label, frame in (("annual", annual), ("quarterly", quarterly)):
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise RuntimeError(
                f"{label.title()} growth parquet missing company identity columns: {missing}"
            )

    annual_identity = annual[required].copy()
    annual_identity["source_s3_path"] = ANNUAL_GROWTH_S3_PATH
    quarterly_identity = quarterly[required].copy()
    quarterly_identity["source_s3_path"] = QUARTERLY_GROWTH_S3_PATH
    identity = pd.concat([annual_identity, quarterly_identity], ignore_index=True)
    identity = identity.dropna(subset=["gvkey", "datadate"])
    identity["gvkey"] = identity["gvkey"].astype(str)
    identity["datadate"] = pd.to_datetime(identity["datadate"]).dt.date

    latest = (
        identity.sort_values(["gvkey", "datadate", "source_s3_path"])
        .groupby("gvkey", as_index=False, dropna=False)
        .tail(1)
        .rename(columns={"datadate": "latest_fundamental_date"})
    )
    latest["updated_at"] = datetime.now(timezone.utc)
    out = latest[
        [
            "gvkey",
            "ticker",
            "company_name",
            "exchange_code",
            "latest_fundamental_date",
            "source_s3_path",
            "updated_at",
        ]
    ].copy()
    duplicates = out.duplicated(["gvkey"]).sum()
    if duplicates:
        raise RuntimeError(f"company_master build produced duplicate GVKEYs: {duplicates:,}")
    print(f"Company master rows built from full fundamental history: {len(out):,}")
    return out


def build_security_master_rows(daily: pd.DataFrame) -> pd.DataFrame:
    identity_columns = [
        "gvkey",
        "iid",
        "ticker",
        "company_name",
        "exchange_code",
        "security_status",
        "issue_type_code",
        "snapshot_date",
        "source_s3_path",
    ]
    missing = [column for column in identity_columns if column not in daily.columns]
    if missing:
        raise RuntimeError(f"Daily metrics parquet missing security master columns: {missing}")

    latest_date = daily["snapshot_date"].max()
    grouped = daily.groupby(["gvkey", "iid"], dropna=False)
    first_seen = grouped["snapshot_date"].min().rename("first_seen_date")
    last_seen = grouped["snapshot_date"].max().rename("last_seen_date")

    latest_identity = (
        daily.sort_values(["gvkey", "iid", "snapshot_date"])
        .groupby(["gvkey", "iid"], as_index=False, dropna=False)
        .tail(1)
        .set_index(["gvkey", "iid"])
    )

    master = latest_identity.join(first_seen).join(last_seen).reset_index()
    master = master.rename(columns={"issue_type_code": "security_type"})
    master["is_active"] = master["last_seen_date"] == latest_date
    master = add_universe_filter_columns(master)
    master["updated_at"] = datetime.now(timezone.utc)

    out = master[
        [
            "gvkey",
            "iid",
            "ticker",
            "company_name",
            "exchange_code",
            "security_status",
            "security_type",
            "is_active",
            "is_excluded_universe",
            "exclusion_reason",
            "first_seen_date",
            "last_seen_date",
            "source_s3_path",
            "updated_at",
        ]
    ].copy()

    duplicates = out.duplicated(["gvkey", "iid"]).sum()
    if duplicates:
        raise RuntimeError(f"security_master build produced duplicate primary keys: {duplicates:,}")

    print(f"Security master rows built: {len(out):,}")
    print(f"Security master active rows built: {int(out['is_active'].sum()):,}")
    print(f"Security master excluded universe rows built: {int(out['is_excluded_universe'].sum()):,}")
    return out


def build_daily_f_confirmation(daily: pd.DataFrame) -> pd.DataFrame:
    from server_pipeline.utils.trading_calendar import next_official_trading_dates

    confirmation = (
        daily[
            [
                "gvkey",
                "iid",
                "snapshot_date",
                "close_price_raw",
                "adjusted_close_price",
                "ma20",
                "ma50",
                "ma100",
            ]
        ]
        .copy()
        .sort_values(["gvkey", "iid", "snapshot_date"])
    )
    grouped = confirmation.groupby(["gvkey", "iid"], dropna=False)
    confirmation["daily_f_confirmed_using_date"] = grouped["snapshot_date"].shift(-1)
    confirmation["future_daily_close_price"] = grouped["close_price_raw"].shift(-1)
    confirmation["future_daily_adjusted_close_price"] = grouped["adjusted_close_price"].shift(-1)
    confirmation["future_daily_ma20"] = grouped["ma20"].shift(-1)
    confirmation["future_daily_ma50"] = grouped["ma50"].shift(-1)
    confirmation["future_daily_ma100"] = grouped["ma100"].shift(-1)

    next_sessions = next_official_trading_dates(
        confirmation["snapshot_date"].min(),
        confirmation["snapshot_date"].max(),
    )
    expected_next = confirmation["snapshot_date"].map(next_sessions)
    has_future_row = (
        confirmation["daily_f_confirmed_using_date"].notna()
        & (confirmation["daily_f_confirmed_using_date"] == expected_next)
    )
    future_columns = [
        "future_daily_close_price",
        "future_daily_adjusted_close_price",
        "future_daily_ma20",
        "future_daily_ma50",
        "future_daily_ma100",
    ]
    confirmation["daily_f_confirmed_using_date"] = (
        confirmation["daily_f_confirmed_using_date"].where(has_future_row, pd.NA)
    )
    for column in future_columns:
        confirmation[column] = confirmation[column].where(has_future_row, pd.NA)

    return confirmation[
        [
            "gvkey",
            "iid",
            "snapshot_date",
            "daily_f_confirmed_using_date",
            "future_daily_ma20",
            "future_daily_ma50",
            "future_daily_ma100",
            "future_daily_close_price",
            "future_daily_adjusted_close_price",
        ]
    ]


def build_weekly_h_confirmation(weekly: pd.DataFrame) -> pd.DataFrame:
    from server_pipeline.utils.trading_calendar import next_official_week_end_dates

    confirmation = (
        weekly[
            [
                "gvkey",
                "iid",
                "week_end_date",
                "weekly_close_price",
                "weekly_ma5",
                "weekly_ma10",
                "weekly_ma30",
            ]
        ]
        .copy()
        .sort_values(["gvkey", "iid", "week_end_date"])
    )
    grouped = confirmation.groupby(["gvkey", "iid"], dropna=False)
    confirmation["weekly_h_confirmed_using_date"] = grouped["week_end_date"].shift(-1)
    confirmation["future_weekly_close_price"] = grouped["weekly_close_price"].shift(-1)
    confirmation["future_weekly_ma5"] = grouped["weekly_ma5"].shift(-1)
    confirmation["future_weekly_ma10"] = grouped["weekly_ma10"].shift(-1)
    confirmation["future_weekly_ma30"] = grouped["weekly_ma30"].shift(-1)

    next_week_ends = next_official_week_end_dates(
        confirmation["week_end_date"].min(),
        confirmation["week_end_date"].max(),
    )
    expected_next = confirmation["week_end_date"].map(next_week_ends)
    has_future_row = (
        confirmation["weekly_h_confirmed_using_date"].notna()
        & (confirmation["weekly_h_confirmed_using_date"] == expected_next)
    )
    future_columns = [
        "future_weekly_close_price",
        "future_weekly_ma5",
        "future_weekly_ma10",
        "future_weekly_ma30",
    ]
    confirmation["weekly_h_confirmed_using_date"] = (
        confirmation["weekly_h_confirmed_using_date"].where(has_future_row, pd.NA)
    )
    for column in future_columns:
        confirmation[column] = confirmation[column].where(has_future_row, pd.NA)

    return confirmation[
        [
            "gvkey",
            "iid",
            "week_end_date",
            "weekly_h_confirmed_using_date",
            "future_weekly_ma5",
            "future_weekly_ma10",
            "future_weekly_ma30",
            "future_weekly_close_price",
        ]
    ]


def validate_daily_future_fields(df: pd.DataFrame) -> None:
    checks = {
        "bad_daily_future_date_rows": (
            df["daily_f_confirmed_using_date"].notna()
            & (df["daily_f_confirmed_using_date"] <= df["snapshot_date"])
        ),
        "bad_daily_null_rows": (
            df["daily_f_confirmed_using_date"].isna()
            & (
                df["future_daily_ma20"].notna()
                | df["future_daily_ma50"].notna()
                | df["future_daily_ma100"].notna()
            )
        ),
    }
    failures = {name: int(mask.sum()) for name, mask in checks.items() if int(mask.sum())}
    if failures:
        formatted = ", ".join(f"{name}={count:,}" for name, count in failures.items())
        raise RuntimeError(f"Daily future input validation failed: {formatted}")

    print("Daily future input validation passed.")
    print(
        "Rows with future daily confirmation inputs: "
        f"{df['daily_f_confirmed_using_date'].notna().sum():,}; "
        f"pending rows: {df['daily_f_confirmed_using_date'].isna().sum():,}"
    )


def validate_weekly_future_fields(df: pd.DataFrame) -> None:
    weekly_calendar = df[["week_start_date", "week_end_date"]].drop_duplicates().copy()
    weekly_calendar["official_week_end_date"] = weekly_calendar["week_start_date"].map(
        official_week_end_trading_date
    )
    bad_official_week_ends = weekly_calendar[
        (weekly_calendar["official_week_end_date"].isna())
        | (weekly_calendar["week_end_date"] != weekly_calendar["official_week_end_date"])
    ]

    weekly_keys = set(
        df[["gvkey", "iid", "week_end_date"]].itertuples(index=False, name=None)
    )
    future_keys = set(
        df[df["weekly_h_confirmed_using_date"].notna()][
            ["gvkey", "iid", "weekly_h_confirmed_using_date"]
        ].itertuples(index=False, name=None)
    )
    missing_future_keys = future_keys - weekly_keys

    bad_official_week_keys = set(
        bad_official_week_ends[["week_start_date", "week_end_date"]]
        .itertuples(index=False, name=None)
    )
    bad_official_week_mask = df.apply(
        lambda row: (row["week_start_date"], row["week_end_date"]) in bad_official_week_keys,
        axis=1,
    )
    missing_future_mask = df.apply(
        lambda row: (
            row["gvkey"],
            row["iid"],
            row["weekly_h_confirmed_using_date"],
        ) in missing_future_keys,
        axis=1,
    )

    checks = {
        "bad_official_week_end_rows": bad_official_week_mask,
        "bad_missing_future_week_rows": missing_future_mask,
        "bad_weekly_future_date_rows": (
            df["weekly_h_confirmed_using_date"].notna()
            & (df["weekly_h_confirmed_using_date"] <= df["week_end_date"])
        ),
        "bad_weekly_null_rows": (
            df["weekly_h_confirmed_using_date"].isna()
            & (
                df["future_weekly_ma5"].notna()
                | df["future_weekly_ma10"].notna()
                | df["future_weekly_ma30"].notna()
            )
        ),
    }
    failures = {name: int(mask.sum()) for name, mask in checks.items() if int(mask.sum())}
    if failures:
        formatted = ", ".join(f"{name}={count:,}" for name, count in failures.items())
        if not bad_official_week_ends.empty:
            print(bad_official_week_ends.to_string(index=False))
        if missing_future_keys:
            print(f"Missing future weekly keys: {sorted(missing_future_keys)[:10]}")
        raise RuntimeError(f"Weekly future input validation failed: {formatted}")

    print("Weekly future input validation passed.")
    print(
        "Rows with future weekly confirmation inputs: "
        f"{df['weekly_h_confirmed_using_date'].notna().sum():,}; "
        f"pending rows: {df['weekly_h_confirmed_using_date'].isna().sum():,}"
    )


def build_security_serving_rows(
    lookback_months: int,
    history_start_date: date | None,
    inspection_trading_days: int = DEFAULT_INSPECTION_TRADING_DAYS,
    weekly_lookback_weeks: int = DEFAULT_WEEKLY_LOOKBACK_WEEKS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, date, date]:
    daily_metric_paths = list_daily_metric_paths()
    if not daily_metric_paths:
        raise RuntimeError(
            f"No daily metric partitions found under "
            f"s3://{S3_BUCKET}/{DAILY_MARKET_METRICS_PREFIX}/"
        )
    latest_daily_date = max(
        pd.to_datetime(item["date"]).date() for item in daily_metric_paths
    )
    explicit_history_start = history_start_date is not None
    if history_start_date is None:
        history_start_date, inspection_start_date = rolling_daily_history_start(
            latest_daily_date,
            lookback_months,
            inspection_trading_days,
        )
        print(
            "No explicit serving-history start supplied; preparing complete "
            f"Condition D history for {inspection_trading_days} inspection "
            f"trading days starting {inspection_start_date}."
        )
        print(f"Daily serving-history start: {history_start_date}")
    if explicit_history_start:
        weekly_history_start_date = week_start_for_date(history_start_date)
    else:
        latest_week_start_date = week_start_for_date(latest_daily_date)
        weekly_history_start_date = latest_week_start_date - timedelta(
            weeks=weekly_lookback_weeks - 1
        )
        print(
            "Weekly serving history uses an independent completed-week cutoff: "
            f"{weekly_history_start_date} ({weekly_lookback_weeks} weeks)"
        )
    expected_first_week_end_date = official_week_end_trading_date(
        weekly_history_start_date
    )
    daily_paths = daily_history_window(daily_metric_paths, history_start_date)
    daily = read_many_parquet(daily_paths)
    print(f"Daily metric rows selected: {len(daily):,}")
    print(f"Daily metric columns: {list(daily.columns)}")

    weekly_paths = list_weekly_metric_paths()
    if not weekly_paths:
        raise RuntimeError(
            f"No weekly metric partitions found under s3://{S3_BUCKET}/{WEEKLY_MARKET_METRICS_PREFIX}/"
        )
    weekly = read_many_parquet(weekly_paths)
    print(f"Weekly metric rows available: {len(weekly):,}")
    print(f"Weekly metric columns: {list(weekly.columns)}")

    daily_required = [
        "date",
        "gvkey",
        "iid",
        "ticker",
        "company_name",
        "exchange_code",
        "security_status",
        "issue_type_code",
        "open_price_raw",
        "high_price_raw",
        "low_price_raw",
        "close_price_raw",
        "adjusted_close_price",
        "volume",
        "volume_ma30",
        "volume_ratio",
        "ma20",
        "ma50",
        "ma100",
        "source_s3_path",
    ]
    weekly_required = [
        "gvkey",
        "iid",
        "week_start_date",
        "week_end_date",
        "weekly_close_price",
        "wma5",
        "wma10",
        "wma30",
    ]
    missing_daily = [column for column in daily_required if column not in daily.columns]
    missing_weekly = [column for column in weekly_required if column not in weekly.columns]
    if missing_daily:
        raise RuntimeError(f"Daily metrics parquet missing expected columns: {missing_daily}")
    if missing_weekly:
        raise RuntimeError(f"Weekly metrics parquet missing expected columns: {missing_weekly}")

    daily["snapshot_date"] = pd.to_datetime(daily["date"]).dt.date
    daily = daily[daily["snapshot_date"] >= history_start_date].copy()
    daily["volume_lookback_end_date"] = daily["snapshot_date"]
    daily["volume_lookback_start_date"] = (
        pd.to_datetime(daily["snapshot_date"]) - pd.DateOffset(months=lookback_months)
    ).dt.date
    daily["gvkey"] = daily["gvkey"].astype(str)
    daily["iid"] = daily["iid"].astype(str)

    master_out = build_security_master_rows(daily)
    daily_f_confirmation = build_daily_f_confirmation(daily)
    daily_merged = daily.merge(
        daily_f_confirmation,
        on=["gvkey", "iid", "snapshot_date"],
        how="left",
    )

    weekly["week_start_date"] = pd.to_datetime(weekly["week_start_date"]).dt.date
    weekly["week_end_date"] = pd.to_datetime(weekly["week_end_date"]).dt.date
    weekly = weekly[weekly["week_start_date"] >= weekly_history_start_date].copy()
    weekly["gvkey"] = weekly["gvkey"].astype(str)
    weekly["iid"] = weekly["iid"].astype(str)

    weekly_calendar = weekly[["week_start_date", "week_end_date"]].drop_duplicates().copy()
    weekly_calendar["official_week_end_date"] = weekly_calendar["week_start_date"].map(
        official_week_end_trading_date
    )
    official_week_mask_by_row = (
        weekly_calendar["official_week_end_date"].notna()
        & (weekly_calendar["week_end_date"] == weekly_calendar["official_week_end_date"])
    )
    official_week_keys = set(
        tuple(row)
        for row in weekly_calendar.loc[
            official_week_mask_by_row,
            ["week_start_date", "week_end_date"],
        ].itertuples(index=False, name=None)
    )
    completed_week_mask = weekly.apply(
        lambda row: (row["week_start_date"], row["week_end_date"]) in official_week_keys,
        axis=1,
    )
    skipped_partial_week_rows = int((~completed_week_mask).sum())
    if skipped_partial_week_rows:
        print(
            "Skipping non-official or incomplete weekly metric rows before serving load: "
            f"{skipped_partial_week_rows:,}"
        )
    weekly = weekly[completed_week_mask].copy()

    first_daily_date = daily["snapshot_date"].min()
    first_week_start_date = weekly["week_start_date"].min()
    first_week_end_date = weekly["week_end_date"].min()
    if explicit_history_start and first_daily_date != history_start_date:
        raise RuntimeError(
            "Daily serving history does not begin on the configured date: "
            f"expected {history_start_date}, found {first_daily_date}."
        )
    if (
        first_week_start_date != weekly_history_start_date
        or first_week_end_date != expected_first_week_end_date
    ):
        raise RuntimeError(
            "Weekly serving history has an unexpected first completed week: "
            f"expected {weekly_history_start_date} to {expected_first_week_end_date}, "
            f"found {first_week_start_date} to {first_week_end_date}."
        )

    if "weekly_open_price" not in weekly.columns:
        weekly["weekly_open_price"] = pd.NA
    if "weekly_high_price" not in weekly.columns:
        weekly["weekly_high_price"] = pd.NA
    if "weekly_low_price" not in weekly.columns:
        weekly["weekly_low_price"] = pd.NA
    if "weekly_volume" not in weekly.columns:
        weekly["weekly_volume"] = pd.NA

    weekly_subset = weekly[
        [
            "gvkey",
            "iid",
            "week_start_date",
            "week_end_date",
            "weekly_open_price",
            "weekly_high_price",
            "weekly_low_price",
            "weekly_close_price",
            "weekly_volume",
            "wma5",
            "wma10",
            "wma30",
            "source_s3_path",
        ]
    ].rename(
        columns={
            "wma5": "weekly_ma5",
            "wma10": "weekly_ma10",
            "wma30": "weekly_ma30",
        }
    ).copy()

    weekly_duplicates = weekly_subset.duplicated(["week_end_date", "gvkey", "iid"]).sum()
    if weekly_duplicates:
        raise RuntimeError(
            "Weekly metrics contain duplicate week_end_date/gvkey/iid keys, "
            f"which would duplicate security_weekly_feature_snapshot rows: {weekly_duplicates:,}"
        )

    weekly_h_confirmation = build_weekly_h_confirmation(weekly_subset)
    weekly_merged = weekly_subset.merge(
        weekly_h_confirmation,
        on=["gvkey", "iid", "week_end_date"],
        how="left",
    )

    now = datetime.now(timezone.utc)
    daily_out = pd.DataFrame(
        {
            "snapshot_date": daily_merged["snapshot_date"],
            "gvkey": daily_merged["gvkey"],
            "iid": daily_merged["iid"],
            "open_price": daily_merged["open_price_raw"],
            "high_price": daily_merged["high_price_raw"],
            "low_price": daily_merged["low_price_raw"],
            "close_price": daily_merged["close_price_raw"],
            "adjusted_close_price": daily_merged["adjusted_close_price"],
            "volume": daily_merged["volume"],
            "volume_ma30": daily_merged["volume_ma30"],
            "volume_ratio": daily_merged["volume_ratio"],
            "volume_lookback_start_date": daily_merged["volume_lookback_start_date"],
            "volume_lookback_end_date": daily_merged["volume_lookback_end_date"],
            "ma20": daily_merged["ma20"],
            "ma50": daily_merged["ma50"],
            "ma100": daily_merged["ma100"],
            "daily_f_confirmed_using_date": daily_merged["daily_f_confirmed_using_date"],
            "future_daily_ma20": daily_merged["future_daily_ma20"],
            "future_daily_ma50": daily_merged["future_daily_ma50"],
            "future_daily_ma100": daily_merged["future_daily_ma100"],
            "future_daily_close_price": daily_merged["future_daily_close_price"],
            "future_daily_adjusted_close_price": daily_merged["future_daily_adjusted_close_price"],
            "source_s3_path": daily_merged["source_s3_path"],
            "updated_at": now,
        }
    )

    weekly_out = pd.DataFrame(
        {
            "week_start_date": weekly_merged["week_start_date"],
            "week_end_date": weekly_merged["week_end_date"],
            "gvkey": weekly_merged["gvkey"],
            "iid": weekly_merged["iid"],
            "weekly_open_price": weekly_merged["weekly_open_price"],
            "weekly_high_price": weekly_merged["weekly_high_price"],
            "weekly_low_price": weekly_merged["weekly_low_price"],
            "weekly_close_price": weekly_merged["weekly_close_price"],
            "weekly_volume": weekly_merged["weekly_volume"],
            "weekly_ma5": weekly_merged["weekly_ma5"],
            "weekly_ma10": weekly_merged["weekly_ma10"],
            "weekly_ma30": weekly_merged["weekly_ma30"],
            "weekly_h_confirmed_using_date": weekly_merged["weekly_h_confirmed_using_date"],
            "future_weekly_ma5": weekly_merged["future_weekly_ma5"],
            "future_weekly_ma10": weekly_merged["future_weekly_ma10"],
            "future_weekly_ma30": weekly_merged["future_weekly_ma30"],
            "future_weekly_close_price": weekly_merged["future_weekly_close_price"],
            "source_s3_path": weekly_merged["source_s3_path"],
            "updated_at": now,
        }
    )

    duplicates = daily_out.duplicated(["snapshot_date", "gvkey", "iid"]).sum()
    if duplicates:
        raise RuntimeError(
            "security_daily_feature_snapshot build produced duplicate primary keys: "
            f"{duplicates:,}"
        )
    weekly_duplicates = weekly_out.duplicated(["week_end_date", "gvkey", "iid"]).sum()
    if weekly_duplicates:
        raise RuntimeError(
            "security_weekly_feature_snapshot build produced duplicate primary keys: "
            f"{weekly_duplicates:,}"
        )

    validate_daily_future_fields(daily_out)
    validate_weekly_future_fields(weekly_out)

    print(f"Security daily feature snapshot rows built: {len(daily_out):,}")
    print(
        "Security daily feature snapshot date range: "
        f"{daily_out['snapshot_date'].min()} to {daily_out['snapshot_date'].max()}"
    )
    print(f"Security weekly feature snapshot rows built: {len(weekly_out):,}")
    print(
        "Security weekly feature snapshot week_end range: "
        f"{weekly_out['week_end_date'].min()} to {weekly_out['week_end_date'].max()}"
    )
    print(
        "Security weekly feature snapshot week_start range: "
        f"{weekly_out['week_start_date'].min()} to {weekly_out['week_start_date'].max()}"
    )
    return (
        master_out,
        daily_out,
        weekly_out,
        history_start_date,
        weekly_history_start_date,
    )


def load_table(
    conn,
    table: str,
    df: pd.DataFrame,
    columns: list[str],
    conflict_columns: list[str],
    insert_only: bool = False,
) -> None:
    before_count = table_count(conn, table)
    unique_key_count = df[conflict_columns].drop_duplicates().shape[0]
    print(f"\nLoading {table}")
    print(f"Rows prepared: {len(df):,}")
    print(f"Unique primary keys prepared: {unique_key_count:,}")
    print(f"Rows before load: {before_count:,}")

    if insert_only:
        copy_dataframe(conn, table, df, columns)
    else:
        upsert_dataframe(conn, table, df, columns, conflict_columns)

    after_count = table_count(conn, table)
    print(f"Rows after load: {after_count:,}")

    if after_count < unique_key_count:
        raise RuntimeError(
            f"Row-count validation failed for {table}: after_count={after_count:,}, "
            f"unique loaded keys={unique_key_count:,}"
        )


def delete_daily_feature_snapshot_window(conn, daily_df: pd.DataFrame) -> None:
    start_date = daily_df["snapshot_date"].min()
    end_date = daily_df["snapshot_date"].max()
    prepared_keys = daily_df[["snapshot_date", "gvkey", "iid"]].drop_duplicates().shape[0]

    print("\nReplacing security_daily_feature_snapshot date window before load")
    print(f"Snapshot date window: {start_date} to {end_date}")
    print(f"Prepared daily snapshot keys in window: {prepared_keys:,}")

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM security_daily_feature_snapshot
            WHERE snapshot_date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        deleted_rows = cur.rowcount

    print(f"Deleted existing security_daily_feature_snapshot rows in window: {deleted_rows:,}")


def delete_weekly_feature_snapshot_window(conn, weekly_df: pd.DataFrame) -> None:
    start_date = weekly_df["week_end_date"].min()
    end_date = weekly_df["week_end_date"].max()
    prepared_keys = weekly_df[["week_end_date", "gvkey", "iid"]].drop_duplicates().shape[0]

    print("\nReplacing security_weekly_feature_snapshot week window before load")
    print(f"Week end date window: {start_date} to {end_date}")
    print(f"Prepared weekly snapshot keys in window: {prepared_keys:,}")

    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM security_weekly_feature_snapshot
            WHERE week_end_date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        deleted_rows = cur.rowcount

    print(f"Deleted existing security_weekly_feature_snapshot rows in window: {deleted_rows:,}")


def prune_daily_feature_history(conn, history_start_date: date) -> None:
    print(
        "Pruning security_daily_feature_snapshot rows before history boundary: "
        f"snapshot_date < {history_start_date}"
    )
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM security_daily_feature_snapshot WHERE snapshot_date < %s",
            (history_start_date,),
        )
        deleted_rows = cur.rowcount
    print(f"Deleted pre-boundary daily feature rows: {deleted_rows:,}")


def prune_weekly_feature_history(conn, history_start_date: date) -> None:
    weekly_start_date = week_start_for_date(history_start_date)
    print(
        "Pruning security_weekly_feature_snapshot rows before history boundary: "
        f"week_start_date < {weekly_start_date}"
    )
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM security_weekly_feature_snapshot WHERE week_start_date < %s",
            (weekly_start_date,),
        )
        deleted_rows = cur.rowcount
    print(f"Deleted pre-boundary weekly feature rows: {deleted_rows:,}")


def validate_security_master_active_count(conn, security_df: pd.DataFrame) -> None:
    latest_snapshot_date = security_df["snapshot_date"].max()
    latest_snapshot_count = (
        security_df[security_df["snapshot_date"] == latest_snapshot_date][["gvkey", "iid"]]
        .drop_duplicates()
        .shape[0]
    )
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM security_master WHERE is_active = true")
        active_master_count = int(cur.fetchone()[0])

    print(f"Latest security snapshot date: {latest_snapshot_date}")
    print(f"Latest security snapshot keys: {latest_snapshot_count:,}")
    print(f"Active security_master rows: {active_master_count:,}")
    if active_master_count < latest_snapshot_count:
        raise RuntimeError(
            "security_master active-row validation failed: "
            f"active_master_count={active_master_count:,}, "
            f"latest_snapshot_count={latest_snapshot_count:,}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load processed S3 feature outputs into Supabase serving tables."
    )
    parser.add_argument(
        "--apply-schema",
        action="store_true",
        help="Run sql/create_supabase_serving_tables.sql before loading.",
    )
    parser.add_argument(
        "--recreate-serving-schema",
        action="store_true",
        help=(
            "Drop and recreate only production serving tables before loading. "
            "Backtest tables are never dropped."
        ),
    )
    parser.add_argument(
        "--lookback-months",
        type=int,
        default=3,
        help="Condition D volume-history interval recorded on daily rows.",
    )
    parser.add_argument(
        "--inspection-trading-days",
        type=int,
        default=DEFAULT_INSPECTION_TRADING_DAYS,
        help=(
            "Recent inspection sessions that must each have a complete daily "
            "lookback. Defaults to 15 trading days."
        ),
    )
    parser.add_argument(
        "--weekly-lookback-weeks",
        type=int,
        default=DEFAULT_WEEKLY_LOOKBACK_WEEKS,
        help=(
            "Completed weekly feature history retained for WMA30 and timing "
            "support. Defaults to 36 weeks."
        ),
    )
    parser.add_argument(
        "--prune-history",
        action="store_true",
        help=(
            "Delete daily and weekly serving rows older than the current load "
            "boundaries. By default, older rows are retained."
        ),
    )
    parser.add_argument(
        "--history-start-date",
        type=date.fromisoformat,
        default=(
            date.fromisoformat(os.environ["SERVING_HISTORY_START_DATE"])
            if os.environ.get("SERVING_HISTORY_START_DATE")
            else None
        ),
        help=(
            "Inclusive serving-history start date. Defaults to "
            "SERVING_HISTORY_START_DATE when set; otherwise uses the rolling "
            "--lookback-months cutoff. Historical loads require sufficient "
            "Supabase storage."
        ),
    )
    parser.add_argument(
        "--allow-large-history-load",
        action="store_true",
        help=(
            "Acknowledge that an explicit historical load can require several "
            "gigabytes of Supabase database storage."
        ),
    )
    parser.add_argument(
        "--only",
        choices=[
            "security",
            "security-master",
            "company-master",
            "daily",
            "weekly",
            "annual",
            "quarterly",
        ],
        help="Load only one serving table.",
    )
    args = parser.parse_args()

    if args.weekly_lookback_weeks < 30:
        parser.error("--weekly-lookback-weeks must be at least 30 for WMA30.")
    if args.inspection_trading_days < 1:
        parser.error("--inspection-trading-days must be at least 1.")

    if args.history_start_date and not args.allow_large_history_load:
        parser.error(
            "--history-start-date requires --allow-large-history-load. "
            "Confirm Supabase storage capacity before proceeding."
        )

    print("Loading processed S3 features into Supabase serving tables.")
    print(f"S3 bucket: {S3_BUCKET}")
    print(
        f"Security serving history start: {args.history_start_date}"
        if args.history_start_date
        else "Security serving history start: rolling lookback"
    )
    print(f"Condition D lookback months: {args.lookback_months}")
    print(f"Inspection trading days supported: {args.inspection_trading_days}")
    print(f"Weekly feature lookback weeks: {args.weekly_lookback_weeks}")
    print("SUPABASE_DB_URL: set" if os.environ.get("SUPABASE_DB_URL") else "SUPABASE_DB_URL: missing")

    with connect_supabase() as conn:
        if args.recreate_serving_schema:
            print("Recreating compact Supabase serving schema...")
            recreate_serving_schema(conn)
        elif args.apply_schema:
            print("Applying Supabase serving schema...")
            apply_schema(conn)

        required_tables = required_tables_for_load(args.only)
        require_tables(conn, required_tables)

        with conn.transaction():
            if args.only in (None, "security", "security-master", "daily", "weekly"):
                (
                    security_master_df,
                    daily_df,
                    weekly_df,
                    effective_history_start_date,
                    effective_weekly_history_start_date,
                ) = build_security_serving_rows(
                    args.lookback_months,
                    args.history_start_date,
                    args.inspection_trading_days,
                    args.weekly_lookback_weeks,
                )

            if args.only in (None, "security", "security-master"):
                print("\nMarking existing security_master rows inactive before upsert...")
                deactivate_security_master(conn)
                load_table(
                    conn,
                    "security_master",
                    security_master_df,
                    [
                        "gvkey",
                        "iid",
                        "ticker",
                        "company_name",
                        "exchange_code",
                        "security_status",
                        "security_type",
                        "is_active",
                        "is_excluded_universe",
                        "exclusion_reason",
                        "first_seen_date",
                        "last_seen_date",
                        "source_s3_path",
                        "updated_at",
                    ],
                    ["gvkey", "iid"],
                )

            if args.only in (None, "company-master"):
                company_master_df = build_company_master_rows()
                load_table(
                    conn,
                    "company_master",
                    company_master_df,
                    [
                        "gvkey",
                        "ticker",
                        "company_name",
                        "exchange_code",
                        "latest_fundamental_date",
                        "source_s3_path",
                        "updated_at",
                    ],
                    ["gvkey"],
                )

            if args.only in (None, "security", "daily"):
                if args.prune_history:
                    prune_daily_feature_history(conn, effective_history_start_date)
                else:
                    print(
                        "Retaining security_daily_feature_snapshot rows before "
                        f"{effective_history_start_date}."
                    )
                delete_daily_feature_snapshot_window(conn, daily_df)
                load_table(
                    conn,
                    "security_daily_feature_snapshot",
                    daily_df,
                    [
                        "snapshot_date",
                        "gvkey",
                        "iid",
                        "open_price",
                        "high_price",
                        "low_price",
                        "close_price",
                        "adjusted_close_price",
                        "volume",
                        "volume_ma30",
                        "volume_ratio",
                        "volume_lookback_start_date",
                        "volume_lookback_end_date",
                        "ma20",
                        "ma50",
                        "ma100",
                        "daily_f_confirmed_using_date",
                        "future_daily_ma20",
                        "future_daily_ma50",
                        "future_daily_ma100",
                        "future_daily_close_price",
                        "future_daily_adjusted_close_price",
                        "source_s3_path",
                        "updated_at",
                    ],
                    ["snapshot_date", "gvkey", "iid"],
                    insert_only=True,
                )
                validate_security_master_active_count(conn, daily_df)

            if args.only in (None, "security", "weekly"):
                if args.prune_history:
                    prune_weekly_feature_history(
                        conn,
                        effective_weekly_history_start_date,
                    )
                else:
                    print(
                        "Retaining security_weekly_feature_snapshot rows before "
                        f"{effective_weekly_history_start_date}."
                    )
                delete_weekly_feature_snapshot_window(conn, weekly_df)
                load_table(
                    conn,
                    "security_weekly_feature_snapshot",
                    weekly_df,
                    [
                        "week_start_date",
                        "week_end_date",
                        "gvkey",
                        "iid",
                        "weekly_open_price",
                        "weekly_high_price",
                        "weekly_low_price",
                        "weekly_close_price",
                        "weekly_volume",
                        "weekly_ma5",
                        "weekly_ma10",
                        "weekly_ma30",
                        "weekly_h_confirmed_using_date",
                        "future_weekly_ma5",
                        "future_weekly_ma10",
                        "future_weekly_ma30",
                        "future_weekly_close_price",
                        "source_s3_path",
                        "updated_at",
                    ],
                    ["week_end_date", "gvkey", "iid"],
                    insert_only=True,
                )

            if args.only in (None, "annual"):
                annual_df = build_annual_rows()
                load_table(
                    conn,
                    "annual_growth_history",
                    annual_df,
                    [
                        "gvkey",
                        "fyear",
                        "datadate",
                        "annual_rank_desc",
                        "annual_revenue",
                        "annual_operating_income",
                        "annual_revenue_growth",
                        "annual_operating_income_growth",
                        "source_extract_date",
                        "source_s3_path",
                        "updated_at",
                    ],
                    ["gvkey", "fyear"],
                )

            if args.only in (None, "quarterly"):
                quarterly_df = build_quarterly_rows()
                load_table(
                    conn,
                    "quarterly_growth_history",
                    quarterly_df,
                    [
                        "gvkey",
                        "fyearq",
                        "fqtr",
                        "datadate",
                        "quarterly_rank_desc",
                        "quarterly_revenue",
                        "quarterly_operating_income",
                        "quarterly_revenue_growth",
                        "quarterly_operating_income_growth",
                        "source_extract_date",
                        "source_s3_path",
                        "updated_at",
                    ],
                    ["gvkey", "fyearq", "fqtr"],
                )

    print("\nSupabase serving load completed.")


if __name__ == "__main__":
    main()

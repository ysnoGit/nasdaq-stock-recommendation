from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BACKTEST_ROOT = Path(__file__).resolve().parents[1]


def require_supabase_db_url() -> str:
    db_url = os.environ.get("SUPABASE_DB_URL")
    if db_url:
        return db_url
    raise RuntimeError(
        "SUPABASE_DB_URL is not set. Set it in your shell profile or run:\n"
        'export SUPABASE_DB_URL="postgresql://..."'
    )


def connect_supabase():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is not installed. Run: python3 -m pip install 'psycopg[binary]'"
        ) from exc

    return psycopg.connect(require_supabase_db_url())


def read_sql_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def apply_sql_file(conn, path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(read_sql_file(path))


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
            "Missing backtest table(s): "
            f"{', '.join(missing)}. Run: bash backtest_lab/scripts/apply_backtest_schema.sh"
        )


def normalize_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        if value.tzinfo:
            return value.to_pydatetime()
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def normalize_records(df: pd.DataFrame) -> list[tuple[Any, ...]]:
    normalized = df.astype(object).where(pd.notna(df), None)
    return [
        tuple(normalize_value(value) for value in row)
        for row in normalized.itertuples(index=False, name=None)
    ]


def upsert_dataframe(
    conn,
    table: str,
    df: pd.DataFrame,
    columns: list[str],
    conflict_columns: list[str],
) -> None:
    if df.empty:
        raise RuntimeError(f"No rows prepared for {table}.")

    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns for {table}: {missing}")

    insert_columns = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    conflict_target = ", ".join(conflict_columns)
    update_columns = [
        column
        for column in columns
        if column not in conflict_columns and column != "created_at"
    ]
    update_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)

    sql = f"""
        INSERT INTO {table} ({insert_columns})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_target})
        DO UPDATE SET {update_clause}
    """

    records = normalize_records(df[columns])
    with conn.cursor() as cur:
        cur.executemany(sql, records)


def delete_date_window(
    conn,
    table: str,
    date_column: str,
    start_date,
    end_date,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {table} WHERE {date_column} BETWEEN %s AND %s",
            (start_date, end_date),
        )
        return int(cur.rowcount)


def run_sql_file(path: Path) -> None:
    statements = [
        statement.strip()
        for statement in read_sql_file(path).split(";")
        if statement.strip()
    ]
    with connect_supabase() as conn:
        with conn.cursor() as cur:
            for result_index, statement in enumerate(statements, start=1):
                cur.execute(statement)
                if cur.description:
                    print(f"\nResult set {result_index}")
                    print([column.name for column in cur.description])
                    for row in cur.fetchall():
                        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a backtest_lab SQL file.")
    parser.add_argument("--sql-file", required=True, type=Path)
    args = parser.parse_args()
    run_sql_file(args.sql_file)


if __name__ == "__main__":
    main()

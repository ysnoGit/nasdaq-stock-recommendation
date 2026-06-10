from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def connect_supabase():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("SUPABASE_DB_URL is not set.")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg: python3 -m pip install 'psycopg[binary]'") from exc
    return psycopg.connect(url)


def execute_sql_file(conn, path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))


def normalize(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.generic):
        return value.item()
    return value


def records(df: pd.DataFrame, columns: list[str]) -> list[tuple[Any, ...]]:
    clean = df[columns].astype(object).where(pd.notna(df[columns]), None)
    return [tuple(normalize(value) for value in row) for row in clean.itertuples(index=False, name=None)]


def upsert_parameter_grid(conn, grid: pd.DataFrame) -> pd.DataFrame:
    columns = list(grid.columns)
    placeholders = ", ".join(["%s"] * len(columns))
    conflict = (
        "annual_growth_pct, quarterly_growth_pct, annual_years, quarter_count, "
        "volume_ratio_threshold, volume_surge_min_days, daily_ma_tolerance_pct, "
        "weekly_ma_tolerance_pct"
    )
    sql = f"""
        INSERT INTO backtest_parameter_set ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT ({conflict}) DO UPDATE SET
            parameter_set_name = EXCLUDED.parameter_set_name,
            start_date = EXCLUDED.start_date,
            end_date = EXCLUDED.end_date
    """
    with conn.cursor() as cur:
        cur.executemany(sql, records(grid, columns))
        cur.execute(
            """
            SELECT *
            FROM backtest_parameter_set
            ORDER BY parameter_set_id
            """
        )
        rows = cur.fetchall()
        names = [column.name for column in cur.description]
    return pd.DataFrame(rows, columns=names)


def replace_outcomes(conn, parameter_set_id: int, outcomes: pd.DataFrame) -> None:
    columns = [
        "parameter_set_id", "screen_type", "signal_date", "f_confirmation_date",
        "g_confirmation_date", "h_confirmation_date", "selected_date", "gvkey", "iid",
        "ticker", "company_name", "selected_price", "selected_adjusted_price",
        "latest_price_date", "latest_price", "latest_adjusted_price",
        "high_price", "high_price_date", "low_price", "low_price_date",
        "return_pct", "max_return_pct", "max_drawdown_pct",
        "trading_days_after_selection", "flag_a", "flag_b", "flag_c", "flag_d",
        "flag_e", "flag_f", "flag_g", "flag_h", "source_result_path",
    ]
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM backtest_selection_outcome WHERE parameter_set_id = %s",
            (parameter_set_id,),
        )
        if outcomes.empty:
            return
        placeholders = ", ".join(["%s"] * len(columns))
        cur.executemany(
            f"INSERT INTO backtest_selection_outcome ({', '.join(columns)}) VALUES ({placeholders})",
            records(outcomes, columns),
        )

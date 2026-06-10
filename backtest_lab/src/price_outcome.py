from __future__ import annotations

from pathlib import Path

import duckdb

from backtest_lab.src.config import DAILY_FEATURE_PATH


def path_sql(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def calculate_price_outcomes(
    con: duckdb.DuckDBPyConnection,
    selection_path: Path,
    source_result_path: str,
) -> duckdb.DuckDBPyRelation:
    return con.sql(
        f"""
        WITH selections AS (
            SELECT * FROM read_parquet('{path_sql(selection_path)}')
        ),
        priced AS (
            SELECT
                s.*,
                d.snapshot_date AS price_date,
                COALESCE(d.adjusted_close_price, d.close_price) AS price,
                d.adjusted_close_price
            FROM selections s
            JOIN read_parquet('{path_sql(DAILY_FEATURE_PATH)}') d
              ON d.gvkey = s.gvkey
             AND d.iid = s.iid
             AND d.snapshot_date >= s.selected_date
        ),
        summary AS (
            SELECT
                parameter_set_id, screen_type, signal_date, f_confirmation_date,
                g_confirmation_date, h_confirmation_date, selected_date, gvkey, iid,
                ticker, company_name, selected_price, selected_adjusted_price,
                flag_a, flag_b, flag_c, flag_d, flag_e, flag_f, flag_g, flag_h,
                MAX(price_date) AS latest_price_date,
                arg_max(price, price_date) AS latest_price,
                arg_max(adjusted_close_price, price_date) AS latest_adjusted_price,
                MAX(price) AS high_price,
                MIN(price) AS low_price,
                arg_min(price, price_date) FILTER (
                    WHERE price_date >= selected_date + INTERVAL '6 months'
                ) AS price_6m,
                MIN(price_date) FILTER (
                    WHERE price_date >= selected_date + INTERVAL '6 months'
                ) AS return_6m_date,
                arg_min(price, price_date) FILTER (
                    WHERE price_date >= selected_date + INTERVAL '1 year'
                ) AS price_1y,
                MIN(price_date) FILTER (
                    WHERE price_date >= selected_date + INTERVAL '1 year'
                ) AS return_1y_date,
                arg_min(price, price_date) FILTER (
                    WHERE price_date >= selected_date + INTERVAL '2 years'
                ) AS price_2y,
                MIN(price_date) FILTER (
                    WHERE price_date >= selected_date + INTERVAL '2 years'
                ) AS return_2y_date,
                COUNT(*)::INTEGER AS trading_days_after_selection
            FROM priced
            GROUP BY ALL
        )
        SELECT
            s.*,
            MIN(p.price_date) FILTER (WHERE p.price = s.high_price) AS high_price_date,
            MIN(p.price_date) FILTER (WHERE p.price = s.low_price) AS low_price_date,
            CASE WHEN s.selected_price <> 0
                THEN (s.latest_price / s.selected_price - 1) * 100 END AS return_pct,
            CASE WHEN s.selected_price <> 0
                THEN (s.high_price / s.selected_price - 1) * 100 END AS max_return_pct,
            CASE WHEN s.selected_price <> 0
                THEN (s.low_price / s.selected_price - 1) * 100 END AS max_drawdown_pct,
            CASE WHEN s.selected_price <> 0 AND s.price_6m IS NOT NULL
                THEN (s.price_6m / s.selected_price - 1) * 100 END AS return_6m_pct,
            CASE WHEN s.selected_price <> 0 AND s.price_1y IS NOT NULL
                THEN (s.price_1y / s.selected_price - 1) * 100 END AS return_1y_pct,
            CASE WHEN s.selected_price <> 0 AND s.price_2y IS NOT NULL
                THEN (s.price_2y / s.selected_price - 1) * 100 END AS return_2y_pct,
            '{source_result_path.replace("'", "''")}' AS source_result_path
        FROM summary s
        JOIN priced p USING (parameter_set_id, screen_type, signal_date, selected_date, gvkey, iid)
        GROUP BY ALL
        """
    )

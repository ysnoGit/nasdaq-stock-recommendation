from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.db import connect_supabase, require_tables  # noqa: E402
from backtest_lab.src.parameter_grid import (  # noqa: E402
    grid_parameter_names,
    result_table_for_parameter_set,
)


CREATE_TABLE_SQL = """
CREATE TABLE {result_table_name} AS
SELECT
    e.selection_event_id,
    e.parameter_set_id,
    p.parameter_set_name,
    p.annual_growth_pct,
    p.quarterly_growth_pct,
    p.annual_years,
    p.quarter_count,
    p.volume_ratio_threshold,
    p.volume_surge_min_days,
    p.daily_ma_tolerance_pct,
    p.weekly_ma_tolerance_pct,
    e.screen_type,
    e.selected_date,
    e.gvkey,
    e.iid,
    e.ticker,
    e.company_name,
    e.selected_price,
    e.selected_adjusted_price,
    e.flag_a,
    e.flag_b,
    e.flag_c,
    e.flag_d,
    e.flag_e,
    e.flag_f,
    e.flag_g,
    e.flag_h,
    COUNT(f.price_flow_id)::integer AS price_flow_periods,
    MIN(f.period_start_date) AS first_price_flow_start_date,
    MAX(f.period_end_date) AS last_price_flow_end_date,
    MAX(f.return_pct) FILTER (WHERE f.period_index = 0) AS first_3m_return_pct
FROM backtest_selection_event e
JOIN backtest_parameter_set p
  ON p.parameter_set_id = e.parameter_set_id
LEFT JOIN backtest_price_flow_3m f
  ON f.selection_event_id = e.selection_event_id
WHERE p.parameter_set_name = %(parameter_set_name)s
GROUP BY
    e.selection_event_id,
    e.parameter_set_id,
    p.parameter_set_name,
    p.annual_growth_pct,
    p.quarterly_growth_pct,
    p.annual_years,
    p.quarter_count,
    p.volume_ratio_threshold,
    p.volume_surge_min_days,
    p.daily_ma_tolerance_pct,
    p.weekly_ma_tolerance_pct,
    e.screen_type,
    e.selected_date,
    e.gvkey,
    e.iid,
    e.ticker,
    e.company_name,
    e.selected_price,
    e.selected_adjusted_price,
    e.flag_a,
    e.flag_b,
    e.flag_c,
    e.flag_d,
    e.flag_e,
    e.flag_f,
    e.flag_g,
    e.flag_h
ORDER BY e.screen_type, e.selected_date, e.gvkey, e.iid;
"""

DATE_INDEX_SQL = "CREATE INDEX {result_table_name}_date_idx ON {result_table_name} (screen_type, selected_date)"
SECURITY_INDEX_SQL = "CREATE INDEX {result_table_name}_security_idx ON {result_table_name} (gvkey, iid)"


def materialize_result_tables(conn, parameter_set_names: list[str]) -> None:
    require_tables(
        conn,
        [
            "backtest_parameter_set",
            "backtest_selection_event",
            "backtest_price_flow_3m",
        ],
    )
    with conn.cursor() as cur:
        for parameter_set_name in parameter_set_names:
            result_table_name = result_table_for_parameter_set(parameter_set_name)
            print(f"Materializing {result_table_name}...")
            cur.execute(f"DROP TABLE IF EXISTS {result_table_name}")
            cur.execute(
                CREATE_TABLE_SQL.format(result_table_name=result_table_name),
                {"parameter_set_name": parameter_set_name},
            )
            cur.execute(DATE_INDEX_SQL.format(result_table_name=result_table_name))
            cur.execute(SECURITY_INDEX_SQL.format(result_table_name=result_table_name))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize one physical result table for each backtest parameter combination."
    )
    parser.add_argument(
        "--parameter-set-name",
        help="Materialize one grid parameter set. If omitted, all 16 result tables are rebuilt.",
    )
    args = parser.parse_args()
    parameter_set_names = (
        [args.parameter_set_name]
        if args.parameter_set_name
        else grid_parameter_names()
    )

    with connect_supabase() as conn:
        with conn.transaction():
            materialize_result_tables(conn, parameter_set_names)

    print(f"Backtest result tables materialized: {len(parameter_set_names):,}")


if __name__ == "__main__":
    main()

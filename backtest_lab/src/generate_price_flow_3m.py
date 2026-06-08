from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.db import connect_supabase, require_tables, table_count  # noqa: E402
from backtest_lab.src.parameter_grid import grid_parameter_names  # noqa: E402


PRICE_FLOW_SQL = """
WITH selected AS (
    SELECT e.*
    FROM backtest_selection_event e
    JOIN backtest_parameter_set p
      ON p.parameter_set_id = e.parameter_set_id
    WHERE p.parameter_set_name = %(parameter_set_name)s
),
latest_daily AS (
    SELECT MAX(snapshot_date) AS latest_snapshot_date
    FROM backtest_daily_feature_snapshot
),
periods AS (
    SELECT
        s.selection_event_id,
        gs.period_index,
        (s.selected_date + (gs.period_index * INTERVAL '3 months'))::date AS period_start_date,
        LEAST(
            (s.selected_date + ((gs.period_index + 1) * INTERVAL '3 months') - INTERVAL '1 day')::date,
            l.latest_snapshot_date
        ) AS period_end_date,
        s.gvkey,
        s.iid
    FROM selected s
    CROSS JOIN latest_daily l
    CROSS JOIN LATERAL generate_series(
        0,
        GREATEST(
            0,
            CEIL((l.latest_snapshot_date - s.selected_date) / 90.0)::integer
        )
    ) AS gs(period_index)
    WHERE s.selected_date <= l.latest_snapshot_date
),
priced AS (
    SELECT
        p.selection_event_id,
        p.period_index,
        p.period_start_date,
        p.period_end_date,
        d.snapshot_date,
        d.adjusted_close_price
    FROM periods p
    JOIN backtest_daily_feature_snapshot d
      ON d.gvkey = p.gvkey
     AND d.iid = p.iid
     AND d.snapshot_date BETWEEN p.period_start_date AND p.period_end_date
),
aggregated AS (
    SELECT
        selection_event_id,
        period_index,
        period_start_date,
        period_end_date,
        COUNT(*)::integer AS trading_days,
        (ARRAY_AGG(adjusted_close_price ORDER BY snapshot_date))[1] AS start_price,
        (ARRAY_AGG(adjusted_close_price ORDER BY snapshot_date DESC))[1] AS end_price,
        MAX(adjusted_close_price) AS high_price,
        MIN(adjusted_close_price) AS low_price,
        AVG(adjusted_close_price) AS avg_price
    FROM priced
    GROUP BY selection_event_id, period_index, period_start_date, period_end_date
)
INSERT INTO backtest_price_flow_3m (
    selection_event_id,
    period_index,
    period_start_date,
    period_end_date,
    trading_days,
    start_price,
    end_price,
    high_price,
    low_price,
    avg_price,
    return_pct
)
SELECT
    selection_event_id,
    period_index,
    period_start_date,
    period_end_date,
    trading_days,
    start_price,
    end_price,
    high_price,
    low_price,
    avg_price,
    CASE
        WHEN start_price IS NOT NULL AND start_price <> 0
        THEN (end_price - start_price) / start_price * 100.0
        ELSE NULL
    END AS return_pct
FROM aggregated
ON CONFLICT (selection_event_id, period_index)
DO UPDATE SET
    period_start_date = EXCLUDED.period_start_date,
    period_end_date = EXCLUDED.period_end_date,
    trading_days = EXCLUDED.trading_days,
    start_price = EXCLUDED.start_price,
    end_price = EXCLUDED.end_price,
    high_price = EXCLUDED.high_price,
    low_price = EXCLUDED.low_price,
    avg_price = EXCLUDED.avg_price,
    return_pct = EXCLUDED.return_pct;
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 3-month price-flow rows for backtest selections.")
    parser.add_argument(
        "--parameter-set-name",
        help="Run one grid parameter set. If omitted, all 16 grid combinations run.",
    )
    args = parser.parse_args()
    parameter_set_names = (
        [args.parameter_set_name]
        if args.parameter_set_name
        else grid_parameter_names()
    )

    with connect_supabase() as conn:
        require_tables(
            conn,
            [
                "backtest_parameter_set",
                "backtest_selection_event",
                "backtest_daily_feature_snapshot",
                "backtest_price_flow_3m",
            ],
        )
        before = table_count(conn, "backtest_price_flow_3m")
        with conn.transaction():
            with conn.cursor() as cur:
                total_affected = 0
                for parameter_set_name in parameter_set_names:
                    print(f"Generating price flow for {parameter_set_name}...")
                    cur.execute(PRICE_FLOW_SQL, {"parameter_set_name": parameter_set_name})
                    total_affected += max(cur.rowcount, 0)
        after = table_count(conn, "backtest_price_flow_3m")

    print(f"Backtest parameter sets processed: {len(parameter_set_names):,}")
    print(f"Rows affected: {total_affected:,}")
    print(f"Price-flow rows before: {before:,}")
    print(f"Price-flow rows after: {after:,}")


if __name__ == "__main__":
    main()

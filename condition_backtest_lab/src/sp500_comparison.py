from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from condition_backtest_lab.src.config import RESULT_DIR, SP500_BENCHMARK_PATH


HORIZONS = (30, 60, 90, 120, 150, 180)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def build_sp500_comparison_outputs(
    performance_dir: Path = RESULT_DIR / "performance",
    benchmark_path: Path = SP500_BENCHMARK_PATH,
) -> None:
    outcomes_path = performance_dir / "performance_outcomes.parquet"
    if not outcomes_path.exists():
        raise RuntimeError(f"Performance outcomes not found: {outcomes_path}")
    if not benchmark_path.exists():
        raise RuntimeError(f"S&P 500 benchmark cache not found: {benchmark_path}")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    outcomes = _sql_path(outcomes_path)
    benchmark = _sql_path(benchmark_path)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE stock_outcomes AS
        SELECT
            *,
            CAST(selection_date AS DATE) AS selection_day,
            CAST(target_date AS DATE) AS target_day
        FROM read_parquet('{outcomes}')
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE sp500 AS
        SELECT
            CAST(benchmark_date AS DATE) AS benchmark_date,
            gvkeyx,
            newnum,
            oldnum,
            sp500_price_close,
            sp500_total_return_index
        FROM read_parquet('{benchmark}')
        WHERE gvkeyx = '000003'
          AND sp500_price_close IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE performance_vs_sp500_outcomes AS
        WITH entry_benchmark AS (
            SELECT
                o.event_id,
                o.horizon_days,
                arg_min(b.benchmark_date, b.benchmark_date) AS sp500_entry_date,
                arg_min(b.sp500_price_close, b.benchmark_date) AS sp500_entry_price_close,
                arg_min(b.sp500_total_return_index, b.benchmark_date)
                    AS sp500_entry_total_return_index
            FROM stock_outcomes o
            LEFT JOIN sp500 b ON b.benchmark_date >= o.selection_day
            GROUP BY o.event_id, o.horizon_days
        ),
        horizon_benchmark AS (
            SELECT
                o.event_id,
                o.horizon_days,
                arg_min(b.benchmark_date, b.benchmark_date) AS sp500_horizon_date,
                arg_min(b.sp500_price_close, b.benchmark_date) AS sp500_horizon_price_close,
                arg_min(b.sp500_total_return_index, b.benchmark_date)
                    AS sp500_horizon_total_return_index
            FROM stock_outcomes o
            LEFT JOIN sp500 b ON b.benchmark_date >= o.target_day
            GROUP BY o.event_id, o.horizon_days
        )
        SELECT
            o.* EXCLUDE (selection_day, target_day),
            e.sp500_entry_date,
            e.sp500_entry_price_close,
            e.sp500_entry_total_return_index,
            h.sp500_horizon_date,
            h.sp500_horizon_price_close,
            h.sp500_horizon_total_return_index,
            CASE
                WHEN e.sp500_entry_price_close IS NOT NULL
                 AND h.sp500_horizon_price_close IS NOT NULL
                 AND e.sp500_entry_price_close <> 0
                    THEN (h.sp500_horizon_price_close / e.sp500_entry_price_close - 1) * 100
            END AS sp500_price_return_pct,
            CASE
                WHEN e.sp500_entry_total_return_index IS NOT NULL
                 AND h.sp500_horizon_total_return_index IS NOT NULL
                 AND e.sp500_entry_total_return_index <> 0
                    THEN (
                        h.sp500_horizon_total_return_index
                        / e.sp500_entry_total_return_index - 1
                    ) * 100
            END AS sp500_total_return_pct,
            CASE
                WHEN o.return_pct IS NOT NULL
                 AND e.sp500_entry_price_close IS NOT NULL
                 AND h.sp500_horizon_price_close IS NOT NULL
                 AND e.sp500_entry_price_close <> 0
                    THEN o.return_pct
                       - (h.sp500_horizon_price_close / e.sp500_entry_price_close - 1) * 100
            END AS excess_vs_sp500_price_pct,
            CASE
                WHEN o.return_pct IS NOT NULL
                 AND e.sp500_entry_total_return_index IS NOT NULL
                 AND h.sp500_horizon_total_return_index IS NOT NULL
                 AND e.sp500_entry_total_return_index <> 0
                    THEN o.return_pct
                       - (
                            h.sp500_horizon_total_return_index
                            / e.sp500_entry_total_return_index - 1
                         ) * 100
            END AS excess_vs_sp500_total_return_pct
        FROM stock_outcomes o
        LEFT JOIN entry_benchmark e USING (event_id, horizon_days)
        LEFT JOIN horizon_benchmark h USING (event_id, horizon_days)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE performance_vs_sp500_summary AS
        SELECT
            group_name,
            parameter_id,
            parameter_name,
            horizon_days,
            COUNT(return_pct) AS completed_observation_count,
            COUNT(sp500_price_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS sp500_price_completed_count,
            COUNT(sp500_total_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS sp500_total_return_completed_count,
            AVG(return_pct) AS average_stock_return_pct,
            MEDIAN(return_pct) AS median_stock_return_pct,
            100.0 * COUNT(*) FILTER (WHERE return_pct > 0)
                / NULLIF(COUNT(return_pct), 0) AS stock_win_rate_pct,
            AVG(sp500_price_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS average_sp500_price_return_pct,
            MEDIAN(sp500_price_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS median_sp500_price_return_pct,
            AVG(sp500_total_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS average_sp500_total_return_pct,
            MEDIAN(sp500_total_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS median_sp500_total_return_pct,
            AVG(excess_vs_sp500_price_pct) AS average_excess_vs_sp500_price_pct,
            MEDIAN(excess_vs_sp500_price_pct) AS median_excess_vs_sp500_price_pct,
            100.0 * COUNT(*) FILTER (WHERE excess_vs_sp500_price_pct > 0)
                / NULLIF(COUNT(excess_vs_sp500_price_pct), 0)
                AS excess_price_win_rate_pct,
            AVG(excess_vs_sp500_total_return_pct)
                AS average_excess_vs_sp500_total_return_pct,
            MEDIAN(excess_vs_sp500_total_return_pct)
                AS median_excess_vs_sp500_total_return_pct,
            100.0 * COUNT(*) FILTER (WHERE excess_vs_sp500_total_return_pct > 0)
                / NULLIF(COUNT(excess_vs_sp500_total_return_pct), 0)
                AS excess_total_return_win_rate_pct
        FROM performance_vs_sp500_outcomes
        GROUP BY group_name, parameter_id, parameter_name, horizon_days
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE group_sp500_summary AS
        SELECT
            group_name,
            horizon_days,
            AVG(sp500_total_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS average_sp500_total_return_pct,
            MEDIAN(sp500_total_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS median_sp500_total_return_pct,
            AVG(sp500_price_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS average_sp500_price_return_pct,
            MEDIAN(sp500_price_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS median_sp500_price_return_pct,
            COUNT(sp500_total_return_pct) FILTER (WHERE return_pct IS NOT NULL)
                AS sp500_total_return_completed_count
        FROM performance_vs_sp500_outcomes
        GROUP BY group_name, horizon_days
        """
    )

    outputs = {
        "performance_vs_sp500_outcomes": (
            "SELECT * FROM performance_vs_sp500_outcomes "
            "ORDER BY group_name, parameter_id, selection_date, gvkey, iid, horizon_days"
        ),
        "performance_vs_sp500_summary": (
            "SELECT * FROM performance_vs_sp500_summary "
            "ORDER BY group_name, parameter_id, horizon_days"
        ),
        "group_sp500_summary": (
            "SELECT * FROM group_sp500_summary ORDER BY group_name, horizon_days"
        ),
    }
    for name, query in outputs.items():
        con.sql(query).write_parquet(
            str(performance_dir / f"{name}.parquet"),
            compression="zstd",
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match component performance events to S&P 500 benchmark returns."
    )
    parser.add_argument("--performance-dir", type=Path, default=RESULT_DIR / "performance")
    parser.add_argument("--benchmark-path", type=Path, default=SP500_BENCHMARK_PATH)
    args = parser.parse_args()
    build_sp500_comparison_outputs(args.performance_dir, args.benchmark_path)
    print(f"S&P comparison outputs: {args.performance_dir.resolve()}")
    print(
        duckdb.sql(
            f"""
            SELECT
                group_name,
                parameter_name,
                horizon_days,
                completed_observation_count,
                ROUND(average_stock_return_pct, 2) AS avg_stock,
                ROUND(average_sp500_total_return_pct, 2) AS avg_sp500_tr,
                ROUND(average_excess_vs_sp500_total_return_pct, 2) AS avg_excess_tr,
                ROUND(excess_total_return_win_rate_pct, 2) AS excess_win_rate
            FROM read_parquet(
                '{_sql_path(args.performance_dir / "performance_vs_sp500_summary.parquet")}'
            )
            ORDER BY group_name, parameter_id, horizon_days
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

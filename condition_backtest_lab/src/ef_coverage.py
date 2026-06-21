from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from condition_backtest_lab.src.config import DAILY_FEATURE_PATH, RESULT_DIR
from server_pipeline.utils.trading_calendar import next_official_trading_dates


DAILY_MA_TOLERANCE_PCT = (1, 2, 3)
TARGET_COMPANY_COUNT = 30


def build_ef_parameter_grid() -> pd.DataFrame:
    rows = []
    for parameter_id, tolerance in enumerate(DAILY_MA_TOLERANCE_PCT, start=1):
        rows.append(
            {
                "parameter_id": parameter_id,
                "parameter_name": f"ef_tol{tolerance}",
                "daily_ma_tolerance_pct": tolerance,
            }
        )
    return pd.DataFrame(rows)


def source_relation(source: str | Path) -> str:
    source_text = str(source)
    if source_text.startswith("s3://") or source_text.endswith(".parquet"):
        escaped_source = source_text.replace("'", "''")
        return f"read_parquet('{escaped_source}')"
    return source_text


def create_ef_coverage_tables(
    con: duckdb.DuckDBPyConnection,
    daily_path: str | Path = DAILY_FEATURE_PATH,
) -> None:
    daily_relation = source_relation(daily_path)
    grid = build_ef_parameter_grid()
    con.register("ef_parameter_grid_df", grid)
    con.execute("CREATE OR REPLACE TEMP TABLE ef_parameter_grid AS SELECT * FROM ef_parameter_grid_df")

    date_range = con.execute(
        f"SELECT MIN(snapshot_date), MAX(snapshot_date) FROM {daily_relation}"
    ).fetchone()
    next_sessions = next_official_trading_dates(date_range[0], date_range[1])
    calendar = pd.DataFrame(
        [
            {"e_date": session, "expected_f_date": next_session}
            for session, next_session in next_sessions.items()
        ]
    )
    con.register("ef_calendar_df", calendar)
    con.execute("CREATE OR REPLACE TEMP TABLE ef_calendar AS SELECT * FROM ef_calendar_df")

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE ef_daily_with_future AS
        SELECT
            d.*,
            c.expected_f_date,
            LEAD(d.snapshot_date) OVER (
                PARTITION BY d.gvkey, d.iid ORDER BY d.snapshot_date
            ) AS next_security_date,
            LEAD(d.adjusted_close_price) OVER (
                PARTITION BY d.gvkey, d.iid ORDER BY d.snapshot_date
            ) AS future_adjusted_close_price,
            LEAD(d.ma20) OVER (
                PARTITION BY d.gvkey, d.iid ORDER BY d.snapshot_date
            ) AS future_ma20,
            LEAD(d.ma50) OVER (
                PARTITION BY d.gvkey, d.iid ORDER BY d.snapshot_date
            ) AS future_ma50
        FROM {daily_relation} d
        LEFT JOIN ef_calendar c ON d.snapshot_date = c.e_date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ef_eligible_security_events AS
        SELECT *
        FROM ef_daily_with_future
        WHERE ma20 IS NOT NULL
          AND ma50 IS NOT NULL
          AND ma100 IS NOT NULL
          AND ma50 <> 0
          AND ma100 <> 0
          AND next_security_date = expected_f_date
          AND future_ma20 IS NOT NULL
          AND future_ma50 IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ef_evaluation_dates AS
        SELECT
            snapshot_date AS evaluation_date,
            COUNT(DISTINCT gvkey) AS eligible_company_count,
            COUNT(DISTINCT (gvkey, iid)) AS eligible_security_count
        FROM ef_eligible_security_events
        GROUP BY snapshot_date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ef_security_evaluation AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.daily_ma_tolerance_pct,
            e.snapshot_date AS e_date,
            e.expected_f_date AS f_confirmation_date,
            e.gvkey,
            e.iid,
            e.ticker,
            e.company_name,
            e.ma20,
            e.ma50,
            e.ma100,
            e.future_ma20,
            e.future_ma50,
            e.future_adjusted_close_price,
            (
                e.ma20 / e.ma50 BETWEEN
                    1 - p.daily_ma_tolerance_pct / 100.0
                    AND 1 + p.daily_ma_tolerance_pct / 100.0
                AND e.ma20 / e.ma100 BETWEEN
                    1 - p.daily_ma_tolerance_pct / 100.0
                    AND 1 + p.daily_ma_tolerance_pct / 100.0
                AND e.ma50 / e.ma100 BETWEEN
                    1 - p.daily_ma_tolerance_pct / 100.0
                    AND 1 + p.daily_ma_tolerance_pct / 100.0
            ) AS flag_e,
            (
                e.ma20 <= e.ma50
                AND e.future_ma20 > e.future_ma50
            ) AS flag_f
        FROM ef_eligible_security_events e
        CROSS JOIN ef_parameter_grid p
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ef_daily_coverage AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.daily_ma_tolerance_pct,
            d.evaluation_date,
            d.eligible_company_count,
            d.eligible_security_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_e)
                AS condition_e_company_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_f)
                AS condition_f_crossover_company_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_e AND e.flag_f)
                AS selected_company_count
        FROM ef_parameter_grid p
        CROSS JOIN ef_evaluation_dates d
        LEFT JOIN ef_security_evaluation e
          ON e.parameter_id = p.parameter_id
         AND e.e_date = d.evaluation_date
        GROUP BY ALL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE ef_coverage_summary AS
        SELECT
            parameter_id,
            parameter_name,
            daily_ma_tolerance_pct,
            COUNT(*) AS included_trading_date_count,
            MIN(evaluation_date) AS first_included_date,
            MAX(evaluation_date) AS last_included_date,
            AVG(eligible_company_count) AS average_eligible_company_count,
            AVG(selected_company_count) AS average_selected_company_count,
            MEDIAN(selected_company_count) AS median_selected_company_count,
            MIN(selected_company_count) AS minimum_selected_company_count,
            MAX(selected_company_count) AS maximum_selected_company_count,
            COUNT(*) FILTER (WHERE selected_company_count = {TARGET_COMPANY_COUNT})
                AS dates_selecting_exactly_30,
            ABS(AVG(selected_company_count) - {TARGET_COMPANY_COUNT})
                AS distance_from_target_30,
            DENSE_RANK() OVER (
                ORDER BY ABS(AVG(selected_company_count) - {TARGET_COMPANY_COUNT}),
                         parameter_id
            ) AS coverage_rank
        FROM ef_daily_coverage
        GROUP BY parameter_id, parameter_name, daily_ma_tolerance_pct
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ef_selections AS
        SELECT *
        FROM ef_security_evaluation
        WHERE flag_e AND flag_f
        """
    )


def write_outputs(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "ef_parameter_grid": "SELECT * FROM ef_parameter_grid ORDER BY parameter_id",
        "ef_daily_coverage": "SELECT * FROM ef_daily_coverage ORDER BY parameter_id, evaluation_date",
        "ef_coverage_summary": "SELECT * FROM ef_coverage_summary ORDER BY coverage_rank, parameter_id",
        "ef_selections": "SELECT * FROM ef_selections ORDER BY parameter_id, e_date, gvkey, iid",
    }
    for name, query in outputs.items():
        relation = con.sql(query)
        relation.write_parquet(str(output_dir / f"{name}.parquet"), compression="zstd")
        if name != "ef_selections":
            relation.write_csv(str(output_dir / f"{name}.csv"), header=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run E&F daily coverage analysis.")
    parser.add_argument("--daily-path", default=str(DAILY_FEATURE_PATH))
    parser.add_argument("--output-dir", type=Path, default=RESULT_DIR / "ef_coverage")
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    create_ef_coverage_tables(con, args.daily_path)
    write_outputs(con, args.output_dir)
    print(f"E&F coverage outputs: {args.output_dir.resolve()}")
    print(
        con.sql(
            """
            SELECT coverage_rank, parameter_name,
                   ROUND(average_selected_company_count, 2) AS average_selected,
                   ROUND(distance_from_target_30, 2) AS distance_from_30,
                   included_trading_date_count, dates_selecting_exactly_30
            FROM ef_coverage_summary
            ORDER BY coverage_rank, parameter_id
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

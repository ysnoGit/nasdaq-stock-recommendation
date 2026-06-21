from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from condition_backtest_lab.src.config import RESULT_DIR, WEEKLY_FEATURE_PATH
from server_pipeline.utils.trading_calendar import next_official_week_end_dates


WEEKLY_MA_TOLERANCE_PCT = (1, 2, 3, 4)
TARGET_COMPANY_COUNT = 30


def build_gh_parameter_grid() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "parameter_id": parameter_id,
                "parameter_name": f"gh_tol{tolerance}",
                "weekly_ma_tolerance_pct": tolerance,
            }
            for parameter_id, tolerance in enumerate(WEEKLY_MA_TOLERANCE_PCT, start=1)
        ]
    )


def source_relation(source: str | Path) -> str:
    source_text = str(source)
    if source_text.startswith("s3://") or source_text.endswith(".parquet"):
        escaped_source = source_text.replace("'", "''")
        return f"read_parquet('{escaped_source}')"
    return source_text


def create_gh_coverage_tables(
    con: duckdb.DuckDBPyConnection,
    weekly_path: str | Path = WEEKLY_FEATURE_PATH,
) -> None:
    weekly_relation = source_relation(weekly_path)
    con.register("gh_parameter_grid_df", build_gh_parameter_grid())
    con.execute("CREATE OR REPLACE TEMP TABLE gh_parameter_grid AS SELECT * FROM gh_parameter_grid_df")
    date_range = con.execute(
        f"SELECT MIN(week_end_date), MAX(week_end_date) FROM {weekly_relation}"
    ).fetchone()
    next_week_ends = next_official_week_end_dates(date_range[0], date_range[1])
    calendar = pd.DataFrame(
        [
            {"g_date": week_end, "expected_h_date": next_week_end}
            for week_end, next_week_end in next_week_ends.items()
        ]
    )
    con.register("gh_calendar_df", calendar)
    con.execute("CREATE OR REPLACE TEMP TABLE gh_calendar AS SELECT * FROM gh_calendar_df")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE gh_eligible_security_events AS
        SELECT w.*, c.expected_h_date
        FROM {weekly_relation} w
        JOIN gh_calendar c ON w.week_end_date = c.g_date
        WHERE w.weekly_ma5 IS NOT NULL
          AND weekly_ma10 IS NOT NULL
          AND weekly_ma30 IS NOT NULL
          AND weekly_ma10 <> 0
          AND weekly_ma30 <> 0
          AND future_weekly_confirmation_date IS NOT NULL
          AND future_weekly_confirmation_date = expected_h_date
          AND future_weekly_ma10 IS NOT NULL
          AND future_weekly_ma30 IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE gh_evaluation_weeks AS
        SELECT
            week_end_date AS evaluation_date,
            COUNT(DISTINCT gvkey) AS eligible_company_count,
            COUNT(DISTINCT (gvkey, iid)) AS eligible_security_count
        FROM gh_eligible_security_events
        GROUP BY week_end_date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE gh_security_evaluation AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.weekly_ma_tolerance_pct,
            w.week_end_date AS g_date,
            w.future_weekly_confirmation_date AS h_confirmation_date,
            w.gvkey,
            w.iid,
            w.weekly_ma5,
            w.weekly_ma10,
            w.weekly_ma30,
            w.future_weekly_ma10,
            w.future_weekly_ma30,
            w.future_weekly_close_price,
            (
                w.weekly_ma5 / w.weekly_ma10 BETWEEN
                    1 - p.weekly_ma_tolerance_pct / 100.0
                    AND 1 + p.weekly_ma_tolerance_pct / 100.0
                AND w.weekly_ma5 / w.weekly_ma30 BETWEEN
                    1 - p.weekly_ma_tolerance_pct / 100.0
                    AND 1 + p.weekly_ma_tolerance_pct / 100.0
                AND w.weekly_ma10 / w.weekly_ma30 BETWEEN
                    1 - p.weekly_ma_tolerance_pct / 100.0
                    AND 1 + p.weekly_ma_tolerance_pct / 100.0
            ) AS flag_g,
            (
                w.weekly_ma10 <= w.weekly_ma30
                AND w.future_weekly_ma10 > w.future_weekly_ma30
            ) AS flag_h
        FROM gh_eligible_security_events w
        CROSS JOIN gh_parameter_grid p
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE gh_weekly_coverage AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.weekly_ma_tolerance_pct,
            d.evaluation_date,
            d.eligible_company_count,
            d.eligible_security_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_g)
                AS condition_g_company_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_h)
                AS condition_h_crossover_company_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_g AND e.flag_h)
                AS selected_company_count
        FROM gh_parameter_grid p
        CROSS JOIN gh_evaluation_weeks d
        LEFT JOIN gh_security_evaluation e
          ON e.parameter_id = p.parameter_id
         AND e.g_date = d.evaluation_date
        GROUP BY ALL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE gh_coverage_summary AS
        SELECT
            parameter_id,
            parameter_name,
            weekly_ma_tolerance_pct,
            COUNT(*) AS included_week_count,
            MIN(evaluation_date) AS first_included_date,
            MAX(evaluation_date) AS last_included_date,
            AVG(eligible_company_count) AS average_eligible_company_count,
            AVG(selected_company_count) AS average_selected_company_count,
            MEDIAN(selected_company_count) AS median_selected_company_count,
            MIN(selected_company_count) AS minimum_selected_company_count,
            MAX(selected_company_count) AS maximum_selected_company_count,
            COUNT(*) FILTER (WHERE selected_company_count = {TARGET_COMPANY_COUNT})
                AS weeks_selecting_exactly_30,
            ABS(AVG(selected_company_count) - {TARGET_COMPANY_COUNT})
                AS distance_from_target_30,
            DENSE_RANK() OVER (
                ORDER BY ABS(AVG(selected_company_count) - {TARGET_COMPANY_COUNT}),
                         parameter_id
            ) AS coverage_rank
        FROM gh_weekly_coverage
        GROUP BY parameter_id, parameter_name, weekly_ma_tolerance_pct
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE gh_selections AS
        SELECT *
        FROM gh_security_evaluation
        WHERE flag_g AND flag_h
        """
    )


def write_outputs(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "gh_parameter_grid": "SELECT * FROM gh_parameter_grid ORDER BY parameter_id",
        "gh_weekly_coverage": "SELECT * FROM gh_weekly_coverage ORDER BY parameter_id, evaluation_date",
        "gh_coverage_summary": "SELECT * FROM gh_coverage_summary ORDER BY coverage_rank, parameter_id",
        "gh_selections": "SELECT * FROM gh_selections ORDER BY parameter_id, g_date, gvkey, iid",
    }
    for name, query in outputs.items():
        relation = con.sql(query)
        relation.write_parquet(str(output_dir / f"{name}.parquet"), compression="zstd")
        if name != "gh_selections":
            relation.write_csv(str(output_dir / f"{name}.csv"), header=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run G&H weekly coverage analysis.")
    parser.add_argument("--weekly-path", default=str(WEEKLY_FEATURE_PATH))
    parser.add_argument("--output-dir", type=Path, default=RESULT_DIR / "gh_coverage")
    args = parser.parse_args()
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    create_gh_coverage_tables(con, args.weekly_path)
    write_outputs(con, args.output_dir)
    print(f"G&H coverage outputs: {args.output_dir.resolve()}")
    print(
        con.sql(
            """
            SELECT coverage_rank, parameter_name,
                   ROUND(average_selected_company_count, 2) AS average_selected,
                   ROUND(distance_from_target_30, 2) AS distance_from_30,
                   included_week_count, weeks_selecting_exactly_30
            FROM gh_coverage_summary
            ORDER BY coverage_rank, parameter_id
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

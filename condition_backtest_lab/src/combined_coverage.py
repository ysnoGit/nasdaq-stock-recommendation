from __future__ import annotations

import argparse
from itertools import product
from pathlib import Path

import duckdb
import pandas as pd

from condition_backtest_lab.src.cd_coverage import (
    VOLUME_RATIO_THRESHOLDS,
    VOLUME_SURGE_MIN_DAYS,
    create_cd_coverage_tables,
)
from condition_backtest_lab.src.config import DAILY_FEATURE_PATH, RESULT_DIR, WEEKLY_FEATURE_PATH
from condition_backtest_lab.src.ef_coverage import DAILY_MA_TOLERANCE_PCT, create_ef_coverage_tables
from condition_backtest_lab.src.gh_coverage import WEEKLY_MA_TOLERANCE_PCT, create_gh_coverage_tables
from server_pipeline.utils.trading_calendar import official_week_end_trading_dates, week_start_for_date


TARGET_COMPANY_COUNT = 30


def combined_grid(tolerances: tuple[int, ...], suffix: str) -> pd.DataFrame:
    rows = []
    for parameter_id, (ratio, days, tolerance) in enumerate(
        product(VOLUME_RATIO_THRESHOLDS, VOLUME_SURGE_MIN_DAYS, tolerances),
        start=1,
    ):
        rows.append(
            {
                "parameter_id": parameter_id,
                "parameter_name": f"cd{suffix}_vr{ratio}_vd{days}_tol{tolerance}",
                "volume_ratio_threshold": ratio,
                "volume_surge_min_days": days,
                f"{'daily' if suffix == 'ef' else 'weekly'}_ma_tolerance_pct": tolerance,
            }
        )
    return pd.DataFrame(rows)


def create_cdef_coverage_tables(
    con: duckdb.DuckDBPyConnection,
    daily_path: str | Path = DAILY_FEATURE_PATH,
) -> None:
    create_cd_coverage_tables(con, daily_path)
    create_ef_coverage_tables(con, daily_path)
    con.register("cdef_grid_df", combined_grid(DAILY_MA_TOLERANCE_PCT, "ef"))
    con.execute("CREATE OR REPLACE TEMP TABLE cdef_parameter_grid AS SELECT * FROM cdef_grid_df")
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cdef_eligible_events AS
        SELECT
            p.*, e.evaluation_date AS signal_date, f.expected_f_date AS confirmation_date,
            e.gvkey, e.iid
        FROM cdef_parameter_grid p
        JOIN cd_eligible_security_evaluation e
          ON e.volume_ratio_threshold = p.volume_ratio_threshold
        JOIN ef_eligible_security_events f
          ON e.evaluation_date = f.snapshot_date
         AND e.gvkey = f.gvkey AND e.iid = f.iid
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cdef_selections AS
        SELECT
            p.*, c.evaluation_date AS signal_date, f.f_confirmation_date AS confirmation_date,
            c.gvkey, c.iid, c.ticker, c.company_name, c.volume_ratio, c.surge_day_count,
            f.ma20, f.ma50, f.ma100, f.future_ma20, f.future_ma50
        FROM cdef_parameter_grid p
        JOIN cd_eligible_security_evaluation c
          ON c.volume_ratio_threshold = p.volume_ratio_threshold
         AND c.flag_c AND c.surge_day_count >= p.volume_surge_min_days
        JOIN ef_security_evaluation f
          ON f.daily_ma_tolerance_pct = p.daily_ma_tolerance_pct
         AND f.e_date = c.evaluation_date
         AND f.gvkey = c.gvkey AND f.iid = c.iid
         AND f.flag_e AND f.flag_f
        """
    )
    create_combined_summary(con, "cdef", "confirmation_date", "trading_date")


def create_cdgh_coverage_tables(
    con: duckdb.DuckDBPyConnection,
    daily_path: str | Path = DAILY_FEATURE_PATH,
    weekly_path: str | Path = WEEKLY_FEATURE_PATH,
) -> None:
    create_cd_coverage_tables(con, daily_path)
    create_gh_coverage_tables(con, weekly_path)
    con.register("cdgh_grid_df", combined_grid(WEEKLY_MA_TOLERANCE_PCT, "gh"))
    con.execute("CREATE OR REPLACE TEMP TABLE cdgh_parameter_grid AS SELECT * FROM cdgh_grid_df")
    date_range = con.execute(
        "SELECT MIN(evaluation_date), MAX(evaluation_date) FROM cd_eligible_security_evaluation"
    ).fetchone()
    weeks = official_week_end_trading_dates(date_range[0], date_range[1])
    daily_dates = con.execute(
        "SELECT DISTINCT evaluation_date FROM cd_eligible_security_evaluation"
    ).fetchall()
    mapping = pd.DataFrame(
        [
            {"signal_date": row[0], "g_date": weeks.get(week_start_for_date(row[0]))}
            for row in daily_dates
            if weeks.get(week_start_for_date(row[0])) is not None
        ]
    )
    con.register("cdgh_date_map_df", mapping)
    con.execute("CREATE OR REPLACE TEMP TABLE cdgh_date_map AS SELECT * FROM cdgh_date_map_df")
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cdgh_eligible_events AS
        SELECT
            p.*, c.evaluation_date AS signal_date, g.week_end_date AS g_date,
            g.future_weekly_confirmation_date AS confirmation_date, c.gvkey, c.iid
        FROM cdgh_parameter_grid p
        JOIN cd_eligible_security_evaluation c
          ON c.volume_ratio_threshold = p.volume_ratio_threshold
        JOIN cdgh_date_map m ON c.evaluation_date = m.signal_date
        JOIN gh_eligible_security_events g
          ON m.g_date = g.week_end_date
         AND c.gvkey = g.gvkey AND c.iid = g.iid
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cdgh_selections AS
        SELECT
            p.*, c.evaluation_date AS signal_date, g.g_date,
            g.h_confirmation_date AS confirmation_date, c.gvkey, c.iid,
            c.ticker, c.company_name, c.volume_ratio, c.surge_day_count,
            g.weekly_ma5, g.weekly_ma10, g.weekly_ma30,
            g.future_weekly_ma10, g.future_weekly_ma30
        FROM cdgh_parameter_grid p
        JOIN cd_eligible_security_evaluation c
          ON c.volume_ratio_threshold = p.volume_ratio_threshold
         AND c.flag_c AND c.surge_day_count >= p.volume_surge_min_days
        JOIN cdgh_date_map m ON c.evaluation_date = m.signal_date
        JOIN gh_security_evaluation g
          ON g.weekly_ma_tolerance_pct = p.weekly_ma_tolerance_pct
         AND m.g_date = g.g_date
         AND c.gvkey = g.gvkey AND c.iid = g.iid
         AND g.flag_g AND g.flag_h
        """
    )
    create_combined_summary(con, "cdgh", "confirmation_date", "week")


def create_combined_summary(
    con: duckdb.DuckDBPyConnection,
    prefix: str,
    date_column: str,
    date_label: str,
) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {prefix}_evaluation_dates AS
        SELECT DISTINCT {date_column} AS evaluation_date
        FROM {prefix}_eligible_events
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {prefix}_eligible_counts AS
        SELECT parameter_id, {date_column} AS evaluation_date,
               COUNT(DISTINCT gvkey) AS eligible_company_count
        FROM {prefix}_eligible_events
        GROUP BY parameter_id, {date_column}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {prefix}_selected_counts AS
        SELECT parameter_id, {date_column} AS evaluation_date,
               COUNT(DISTINCT gvkey) AS selected_company_count
        FROM {prefix}_selections
        GROUP BY parameter_id, {date_column}
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {prefix}_coverage AS
        SELECT
            p.*, d.evaluation_date,
            COALESCE(e.eligible_company_count, 0) AS eligible_company_count,
            COALESCE(s.selected_company_count, 0) AS selected_company_count
        FROM {prefix}_parameter_grid p
        CROSS JOIN {prefix}_evaluation_dates d
        LEFT JOIN {prefix}_eligible_counts e
          ON e.parameter_id = p.parameter_id AND e.evaluation_date = d.evaluation_date
        LEFT JOIN {prefix}_selected_counts s
          ON s.parameter_id = p.parameter_id AND s.evaluation_date = d.evaluation_date
        """
    )
    count_name = "included_trading_date_count" if date_label == "trading_date" else "included_week_count"
    exact_name = "dates_selecting_exactly_30" if date_label == "trading_date" else "weeks_selecting_exactly_30"
    tolerance_column = "daily_ma_tolerance_pct" if prefix == "cdef" else "weekly_ma_tolerance_pct"
    parameter_columns = (
        f"parameter_id, parameter_name, volume_ratio_threshold, "
        f"volume_surge_min_days, {tolerance_column}"
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE {prefix}_coverage_summary AS
        SELECT
            {parameter_columns},
            COUNT(*) AS {count_name},
            MIN(evaluation_date) AS first_included_date,
            MAX(evaluation_date) AS last_included_date,
            AVG(eligible_company_count) AS average_eligible_company_count,
            AVG(selected_company_count) AS average_selected_company_count,
            MEDIAN(selected_company_count) AS median_selected_company_count,
            MIN(selected_company_count) AS minimum_selected_company_count,
            MAX(selected_company_count) AS maximum_selected_company_count,
            COUNT(*) FILTER (WHERE selected_company_count = {TARGET_COMPANY_COUNT}) AS {exact_name},
            ABS(AVG(selected_company_count) - {TARGET_COMPANY_COUNT}) AS distance_from_target_30,
            DENSE_RANK() OVER (
                ORDER BY ABS(AVG(selected_company_count) - {TARGET_COMPANY_COUNT}), parameter_id
            ) AS coverage_rank
        FROM {prefix}_coverage
        GROUP BY {parameter_columns}
        """
    )


def write_outputs(con: duckdb.DuckDBPyConnection, prefix: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ["parameter_grid", "coverage", "coverage_summary", "selections"]:
        table = f"{prefix}_{name}"
        relation = con.sql(f"SELECT * FROM {table}")
        relation.write_parquet(str(output_dir / f"{table}.parquet"), compression="zstd")
        if name != "selections":
            relation.write_csv(str(output_dir / f"{table}.csv"), header=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run combined component coverage analysis.")
    parser.add_argument("screen", choices=["cdef", "cdgh"])
    parser.add_argument("--daily-path", default=str(DAILY_FEATURE_PATH))
    parser.add_argument("--weekly-path", default=str(WEEKLY_FEATURE_PATH))
    args = parser.parse_args()
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    if args.screen == "cdef":
        create_cdef_coverage_tables(con, args.daily_path)
    else:
        create_cdgh_coverage_tables(con, args.daily_path, args.weekly_path)
    write_outputs(con, args.screen, RESULT_DIR / f"{args.screen}_coverage")
    print(
        con.sql(
            f"""
            SELECT coverage_rank, parameter_name,
                   ROUND(average_selected_company_count, 2) AS average_selected,
                   ROUND(distance_from_target_30, 2) AS distance_from_30
            FROM {args.screen}_coverage_summary
            ORDER BY coverage_rank, parameter_id
            LIMIT 10
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from condition_backtest_lab.src.config import DAILY_FEATURE_PATH, REPORT_DIR, RESULT_DIR


GROUPS = {
    "ab": (
        "evaluation_date",
        "ab_selections.parquet",
        "ab_common_window_summary.parquet",
        "common_window_coverage_rank",
    ),
    "cd": ("evaluation_date", "cd_selections.parquet", "cd_coverage_summary.parquet", "coverage_rank"),
    "ef": ("f_confirmation_date", "ef_selections.parquet", "ef_coverage_summary.parquet", "coverage_rank"),
    "gh": ("h_confirmation_date", "gh_selections.parquet", "gh_coverage_summary.parquet", "coverage_rank"),
    "cdef": ("confirmation_date", "cdef_selections.parquet", "cdef_coverage_summary.parquet", "coverage_rank"),
    "cdgh": ("confirmation_date", "cdgh_selections.parquet", "cdgh_coverage_summary.parquet", "coverage_rank"),
}
HORIZONS = (30, 60, 90, 120, 150, 180)
COOLDOWN_DAYS = 180


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def apply_cooldown(events: pd.DataFrame, cooldown_days: int = COOLDOWN_DAYS) -> pd.DataFrame:
    retained = []
    keys = ["group_name", "parameter_id", "gvkey", "iid"]
    events = events.sort_values(keys + ["selection_date", "ticker"], kind="stable")
    for _, group in events.groupby(keys, dropna=False, sort=False):
        last_retained = None
        for index, row in group.iterrows():
            selection_date = pd.Timestamp(row["selection_date"])
            if last_retained is None or (selection_date - last_retained).days >= cooldown_days:
                retained.append(index)
                last_retained = selection_date
    return events.loc[retained].sort_values(
        ["group_name", "parameter_id", "selection_date", "gvkey", "iid"],
        kind="stable",
    )


def build_performance_outputs(
    output_dir: Path,
    daily_path: Path = DAILY_FEATURE_PATH,
    result_dir: Path = RESULT_DIR,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    daily = _sql_path(daily_path)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE daily_prices AS
        SELECT
            CAST(snapshot_date AS DATE) AS price_date,
            CAST(gvkey AS VARCHAR) AS gvkey,
            CAST(iid AS VARCHAR) AS iid,
            ticker,
            company_name,
            COALESCE(adjusted_close_price, close_price) AS price
        FROM read_parquet('{daily}')
        WHERE gvkey IS NOT NULL
          AND iid IS NOT NULL
          AND COALESCE(adjusted_close_price, close_price) IS NOT NULL
          AND COALESCE(adjusted_close_price, close_price) <> 0
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE security_price_depth AS
        SELECT gvkey, iid, arg_max(ticker, price_date) AS ticker,
               COUNT(*) AS price_observation_count
        FROM daily_prices
        GROUP BY gvkey, iid
        """
    )

    standardized_frames = []
    top_frames = []
    for group_name, (date_column, selection_file, summary_file, rank_column) in GROUPS.items():
        group_dir = result_dir / f"{group_name}_coverage"
        selections = _sql_path(group_dir / selection_file)
        summary = _sql_path(group_dir / summary_file)
        top = con.sql(
            f"""
            SELECT
                '{group_name}' AS group_name,
                {rank_column} AS coverage_rank,
                * EXCLUDE ({rank_column})
            FROM read_parquet('{summary}')
            WHERE {rank_column} <= 3
            ORDER BY {rank_column}, parameter_id
            """
        ).df()
        top_frames.append(top)
        con.register(f"{group_name}_top_df", top[["parameter_id"]])

        selection_columns = {
            row[0]
            for row in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{selections}')"
            ).fetchall()
        }
        iid_expression = "CAST(s.iid AS VARCHAR)" if "iid" in selection_columns else "CAST(NULL AS VARCHAR)"
        ticker_expression = "s.ticker" if "ticker" in selection_columns else "CAST(NULL AS VARCHAR)"
        company_expression = (
            "s.company_name" if "company_name" in selection_columns else "CAST(NULL AS VARCHAR)"
        )
        standardized = con.sql(
            f"""
            SELECT
                '{group_name}' AS group_name,
                s.parameter_id,
                s.parameter_name,
                CAST(s.{date_column} AS DATE) AS selection_date,
                CAST(s.gvkey AS VARCHAR) AS gvkey,
                {iid_expression} AS iid,
                {ticker_expression} AS ticker,
                {company_expression} AS company_name
            FROM read_parquet('{selections}') s
            JOIN {group_name}_top_df t USING (parameter_id)
            """
        ).df()
        standardized_frames.append(standardized)

    all_events = pd.concat(standardized_frames, ignore_index=True)
    top_parameters = pd.concat(top_frames, ignore_index=True)
    con.register("all_events_df", all_events)

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE events_with_security AS
        WITH candidates AS (
            SELECT
                e.*,
                p.iid AS candidate_iid,
                p.ticker AS candidate_ticker,
                p.price_observation_count,
                ROW_NUMBER() OVER (
                    PARTITION BY e.group_name, e.parameter_id, e.selection_date, e.gvkey
                    ORDER BY
                        CASE WHEN e.iid IS NOT NULL AND p.iid = e.iid THEN 0 ELSE 1 END,
                        CASE WHEN e.ticker IS NOT NULL AND p.ticker = e.ticker THEN 0 ELSE 1 END,
                        CASE WHEN p.iid = '01' THEN 0 ELSE 1 END,
                        p.price_observation_count DESC,
                        p.iid
                ) AS security_rank
            FROM all_events_df e
            JOIN security_price_depth p ON p.gvkey = e.gvkey
            WHERE e.iid IS NULL OR p.iid = e.iid
        )
        SELECT
            group_name, parameter_id, parameter_name, selection_date, gvkey,
            candidate_iid AS iid,
            COALESCE(ticker, candidate_ticker) AS ticker,
            company_name
        FROM candidates
        WHERE security_rank = 1
        """
    )
    mapped_events = con.sql("SELECT * FROM events_with_security").df()
    retained = apply_cooldown(mapped_events)
    con.register("retained_events_df", retained)
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE retained_events AS
        SELECT
            ROW_NUMBER() OVER (
                ORDER BY group_name, parameter_id, selection_date, gvkey, iid
            ) AS event_id,
            *
        FROM retained_events_df
        """
    )

    horizon_values = ", ".join(f"({days})" for days in HORIZONS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE performance_outcomes AS
        WITH horizons(horizon_days) AS (VALUES {horizon_values}),
        entries AS (
            SELECT
                e.*,
                arg_min(p.price_date, p.price_date) AS entry_date,
                arg_min(p.price, p.price_date) AS entry_price
            FROM retained_events e
            JOIN daily_prices p
              ON p.gvkey = e.gvkey AND p.iid = e.iid
             AND p.price_date >= e.selection_date
            GROUP BY ALL
        ),
        measured AS (
            SELECT
                e.*,
                h.horizon_days,
                e.selection_date + h.horizon_days * INTERVAL 1 DAY AS target_date,
                arg_min(p.price_date, p.price_date) AS horizon_price_date,
                arg_min(p.price, p.price_date) AS horizon_price
            FROM entries e
            CROSS JOIN horizons h
            LEFT JOIN daily_prices p
              ON p.gvkey = e.gvkey AND p.iid = e.iid
             AND p.price_date >= e.selection_date + h.horizon_days * INTERVAL 1 DAY
            GROUP BY ALL
        )
        SELECT
            *,
            CASE WHEN horizon_price IS NOT NULL AND entry_price <> 0
                THEN (horizon_price / entry_price - 1) * 100
            END AS return_pct
        FROM measured
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE performance_summary AS
        SELECT
            group_name,
            parameter_id,
            parameter_name,
            horizon_days,
            COUNT(*) AS retained_event_count,
            COUNT(return_pct) AS completed_observation_count,
            COUNT(DISTINCT gvkey) FILTER (WHERE return_pct IS NOT NULL)
                AS completed_unique_company_count,
            MIN(selection_date) FILTER (WHERE return_pct IS NOT NULL)
                AS first_completed_selection_date,
            MAX(selection_date) FILTER (WHERE return_pct IS NOT NULL)
                AS last_completed_selection_date,
            AVG(return_pct) AS average_return_pct,
            MEDIAN(return_pct) AS median_return_pct,
            100.0 * COUNT(*) FILTER (WHERE return_pct > 0) / NULLIF(COUNT(return_pct), 0)
                AS win_rate_pct,
            STDDEV_SAMP(return_pct) AS return_stddev_pct,
            MIN(return_pct) AS minimum_return_pct,
            MAX(return_pct) AS maximum_return_pct
        FROM performance_outcomes
        GROUP BY group_name, parameter_id, parameter_name, horizon_days
        """
    )

    con.register("top_parameters_df", top_parameters)
    outputs = {
        "top_coverage_parameters": "SELECT * FROM top_parameters_df ORDER BY group_name, coverage_rank",
        "retained_selections": "SELECT * FROM retained_events ORDER BY group_name, parameter_id, selection_date, gvkey, iid",
        "performance_outcomes": "SELECT * FROM performance_outcomes ORDER BY group_name, parameter_id, selection_date, gvkey, iid, horizon_days",
        "performance_summary": "SELECT * FROM performance_summary ORDER BY group_name, parameter_id, horizon_days",
    }
    for name, query in outputs.items():
        relation = con.sql(query)
        relation.write_parquet(str(output_dir / f"{name}.parquet"), compression="zstd")
        relation.write_csv(str(output_dir / f"{name}.csv"), header=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run component-group performance analysis.")
    parser.add_argument("--daily-path", type=Path, default=DAILY_FEATURE_PATH)
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    parser.add_argument("--output-dir", type=Path, default=RESULT_DIR / "performance")
    args = parser.parse_args()
    build_performance_outputs(args.output_dir, args.daily_path, args.result_dir)
    print(f"Performance outputs: {args.output_dir.resolve()}")
    print(
        duckdb.sql(
            f"""
            SELECT group_name, parameter_name, horizon_days,
                   completed_observation_count,
                   ROUND(average_return_pct, 2) AS avg_return,
                   ROUND(median_return_pct, 2) AS median_return,
                   ROUND(win_rate_pct, 2) AS win_rate
            FROM read_parquet('{_sql_path(args.output_dir / "performance_summary.parquet")}')
            ORDER BY group_name, parameter_id, horizon_days
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

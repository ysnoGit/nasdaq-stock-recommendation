from __future__ import annotations

import argparse
from datetime import date
from itertools import product
from pathlib import Path

import duckdb
import pandas as pd

from condition_backtest_lab.src.config import DAILY_FEATURE_PATH, RESULT_DIR


VOLUME_RATIO_THRESHOLDS = (4, 5, 10, 15, 20, 25)
VOLUME_SURGE_MIN_DAYS = (3, 5, 7)
TARGET_COMPANY_COUNT = 30


def build_cd_parameter_grid() -> pd.DataFrame:
    rows = []
    for parameter_id, (volume_ratio, surge_days) in enumerate(
        product(VOLUME_RATIO_THRESHOLDS, VOLUME_SURGE_MIN_DAYS),
        start=1,
    ):
        rows.append(
            {
                "parameter_id": parameter_id,
                "parameter_name": f"cd_vr{volume_ratio}_vd{surge_days}",
                "volume_ratio_threshold": volume_ratio,
                "volume_surge_min_days": surge_days,
            }
        )
    grid = pd.DataFrame(rows)
    if len(grid) != 18:
        raise RuntimeError(f"Expected 18 C&D parameter combinations, built {len(grid)}.")
    return grid


def source_relation(source: str | Path) -> str:
    source_text = str(source)
    if source_text.startswith("s3://") or source_text.endswith(".parquet"):
        escaped = source_text.replace("'", "''")
        return f"read_parquet('{escaped}')"
    return source_text


def create_cd_coverage_tables(
    con: duckdb.DuckDBPyConnection,
    daily_path: str | Path = DAILY_FEATURE_PATH,
    start_date: date | None = None,
    end_date: date | None = None,
) -> None:
    daily_relation = source_relation(daily_path)
    grid = build_cd_parameter_grid()
    thresholds = pd.DataFrame({"volume_ratio_threshold": VOLUME_RATIO_THRESHOLDS})
    con.register("cd_parameter_grid_df", grid)
    con.register("cd_threshold_df", thresholds)
    con.execute("CREATE OR REPLACE TEMP TABLE cd_parameter_grid AS SELECT * FROM cd_parameter_grid_df")
    con.execute("CREATE OR REPLACE TEMP TABLE cd_thresholds AS SELECT * FROM cd_threshold_df")

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE cd_daily_base AS
        SELECT
            CAST(snapshot_date AS DATE) AS evaluation_date,
            CAST(gvkey AS VARCHAR) AS gvkey,
            CAST(iid AS VARCHAR) AS iid,
            ticker,
            company_name,
            volume,
            volume_ma30,
            volume_ratio,
            COUNT(volume) OVER (
                PARTITION BY gvkey, iid
                ORDER BY snapshot_date
                ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
            ) AS prior_volume_observation_count,
            MIN(CAST(snapshot_date AS DATE)) OVER (
                PARTITION BY gvkey, iid
            ) AS first_available_date
        FROM {daily_relation}
        WHERE gvkey IS NOT NULL
          AND iid IS NOT NULL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cd_threshold_evaluation AS
        SELECT
            d.*,
            t.volume_ratio_threshold,
            COUNT(*) FILTER (
                WHERE d.volume_ratio >= t.volume_ratio_threshold
            ) OVER (
                PARTITION BY d.gvkey, d.iid, t.volume_ratio_threshold
                ORDER BY d.evaluation_date
                RANGE BETWEEN INTERVAL 3 MONTH PRECEDING AND CURRENT ROW
            ) AS surge_day_count,
            d.volume_ratio >= t.volume_ratio_threshold AS flag_c
        FROM cd_daily_base d
        CROSS JOIN cd_thresholds t
        """
    )

    date_filters = []
    if start_date is not None:
        date_filters.append(f"evaluation_date >= DATE '{start_date}'")
    if end_date is not None:
        date_filters.append(f"evaluation_date <= DATE '{end_date}'")
    optional_filter = ""
    if date_filters:
        optional_filter = "AND " + " AND ".join(date_filters)

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE cd_eligible_security_evaluation AS
        SELECT *
        FROM cd_threshold_evaluation
        WHERE volume_ratio IS NOT NULL
          AND prior_volume_observation_count = 30
          AND first_available_date <= evaluation_date - INTERVAL 3 MONTH
          {optional_filter}
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cd_evaluation_dates AS
        SELECT
            evaluation_date,
            COUNT(DISTINCT gvkey) AS eligible_company_count,
            COUNT(DISTINCT (gvkey, iid)) AS eligible_security_count
        FROM cd_eligible_security_evaluation
        GROUP BY evaluation_date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cd_daily_coverage AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.volume_ratio_threshold,
            p.volume_surge_min_days,
            d.evaluation_date,
            d.eligible_company_count,
            d.eligible_security_count,
            COUNT(DISTINCT e.gvkey) FILTER (WHERE e.flag_c)
                AS condition_c_company_count,
            COUNT(DISTINCT e.gvkey) FILTER (
                WHERE e.surge_day_count >= p.volume_surge_min_days
            ) AS condition_d_company_count,
            COUNT(DISTINCT e.gvkey) FILTER (
                WHERE e.flag_c
                  AND e.surge_day_count >= p.volume_surge_min_days
            ) AS selected_company_count
        FROM cd_parameter_grid p
        CROSS JOIN cd_evaluation_dates d
        LEFT JOIN cd_eligible_security_evaluation e
          ON e.evaluation_date = d.evaluation_date
         AND e.volume_ratio_threshold = p.volume_ratio_threshold
        GROUP BY
            p.parameter_id,
            p.parameter_name,
            p.volume_ratio_threshold,
            p.volume_surge_min_days,
            d.evaluation_date,
            d.eligible_company_count,
            d.eligible_security_count
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE cd_coverage_summary AS
        SELECT
            parameter_id,
            parameter_name,
            volume_ratio_threshold,
            volume_surge_min_days,
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
        FROM cd_daily_coverage
        GROUP BY
            parameter_id,
            parameter_name,
            volume_ratio_threshold,
            volume_surge_min_days
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE cd_selections AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.volume_ratio_threshold,
            p.volume_surge_min_days,
            e.evaluation_date,
            e.gvkey,
            e.iid,
            e.ticker,
            e.company_name,
            e.volume,
            e.volume_ma30,
            e.volume_ratio,
            e.prior_volume_observation_count,
            e.surge_day_count,
            TRUE AS flag_c,
            TRUE AS flag_d
        FROM cd_parameter_grid p
        JOIN cd_eligible_security_evaluation e
          ON e.volume_ratio_threshold = p.volume_ratio_threshold
         AND e.flag_c
         AND e.surge_day_count >= p.volume_surge_min_days
        """
    )


def write_outputs(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "cd_parameter_grid": "SELECT * FROM cd_parameter_grid ORDER BY parameter_id",
        "cd_daily_coverage": (
            "SELECT * FROM cd_daily_coverage ORDER BY parameter_id, evaluation_date"
        ),
        "cd_coverage_summary": (
            "SELECT * FROM cd_coverage_summary ORDER BY coverage_rank, parameter_id"
        ),
        "cd_selections": (
            "SELECT * FROM cd_selections "
            "ORDER BY parameter_id, evaluation_date, gvkey, iid"
        ),
    }
    for name, query in outputs.items():
        relation = con.sql(query)
        relation.write_parquet(str(output_dir / f"{name}.parquet"), compression="zstd")
        if name != "cd_selections":
            relation.write_csv(str(output_dir / f"{name}.csv"), header=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run C&D daily coverage analysis.")
    parser.add_argument("--daily-path", default=str(DAILY_FEATURE_PATH))
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output-dir", type=Path, default=RESULT_DIR / "cd_coverage")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date) if args.start_date else None
    end_date = date.fromisoformat(args.end_date) if args.end_date else None
    if start_date is not None and end_date is not None and start_date > end_date:
        raise RuntimeError("Start date must be on or before end date.")

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    create_cd_coverage_tables(con, args.daily_path, start_date, end_date)
    write_outputs(con, args.output_dir)

    print(f"C&D coverage outputs: {args.output_dir.resolve()}")
    print(
        con.sql(
            """
            SELECT
                coverage_rank,
                parameter_name,
                ROUND(average_selected_company_count, 2) AS average_selected,
                ROUND(distance_from_target_30, 2) AS distance_from_30,
                included_trading_date_count,
                dates_selecting_exactly_30
            FROM cd_coverage_summary
            ORDER BY coverage_rank, parameter_id
            LIMIT 15
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from datetime import date
from itertools import product
from pathlib import Path

import duckdb
import pandas as pd

from backtest_lab.src.config import ANNUAL_GROWTH_S3_PATH, QUARTERLY_GROWTH_S3_PATH
from condition_backtest_lab.src.config import RESULT_DIR
from server_pipeline.s3_duckdb import connect_duckdb_with_s3


ANNUAL_GROWTH_PCT = (3, 5, 10, 15, 20)
ANNUAL_YEARS = (2, 3, 4)
QUARTERLY_GROWTH_PCT = (3, 5, 10, 15, 20)
QUARTER_COUNTS = (2, 3, 4, 5)
TARGET_COMPANY_COUNT = 30
DEFAULT_START_DATE = date(2017, 1, 1)
DEFAULT_END_DATE = date(2025, 12, 31)


def build_ab_parameter_grid() -> pd.DataFrame:
    rows = []
    for parameter_id, values in enumerate(
        product(
            ANNUAL_GROWTH_PCT,
            ANNUAL_YEARS,
            QUARTERLY_GROWTH_PCT,
            QUARTER_COUNTS,
        ),
        start=1,
    ):
        annual_pct, annual_years, quarterly_pct, quarter_count = values
        rows.append(
            {
                "parameter_id": parameter_id,
                "parameter_name": (
                    f"ab_ag{annual_pct}_ay{annual_years}"
                    f"_qg{quarterly_pct}_qc{quarter_count}"
                ),
                "annual_growth_pct": annual_pct,
                "annual_years": annual_years,
                "quarterly_growth_pct": quarterly_pct,
                "quarter_count": quarter_count,
            }
        )
    grid = pd.DataFrame(rows)
    if len(grid) != 300:
        raise RuntimeError(f"Expected 300 A&B parameter combinations, built {len(grid)}.")
    return grid


def source_relation(source: str) -> str:
    if source.startswith("s3://") or source.endswith(".parquet"):
        escaped = source.replace("'", "''")
        return f"read_parquet('{escaped}')"
    return source


def create_ab_coverage_tables(
    con: duckdb.DuckDBPyConnection,
    start_date: date,
    end_date: date,
    annual_path: str = ANNUAL_GROWTH_S3_PATH,
    quarterly_path: str = QUARTERLY_GROWTH_S3_PATH,
) -> None:
    annual_relation = source_relation(annual_path)
    quarterly_relation = source_relation(quarterly_path)
    grid = build_ab_parameter_grid()
    con.register("ab_parameter_grid_df", grid)
    con.execute("CREATE OR REPLACE TEMP TABLE ab_parameter_grid AS SELECT * FROM ab_parameter_grid_df")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE evaluation_quarters AS
        SELECT CAST(
            date_trunc('quarter', quarter_start)
            + INTERVAL 3 MONTH - INTERVAL 1 DAY
            AS DATE
        ) AS evaluation_date
        FROM generate_series(
            DATE '{start_date}',
            DATE '{end_date}',
            INTERVAL 3 MONTH
        ) AS dates(quarter_start)
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE annual_periods AS
        SELECT
            *,
            LAG(fyear) OVER (
                PARTITION BY gvkey
                ORDER BY fyear
            ) AS previous_available_fyear
        FROM (
            SELECT
                CAST(gvkey AS VARCHAR) AS gvkey,
                CAST(datadate AS DATE) AS datadate,
                fyear,
                ticker,
                company_name,
                annual_revenue_growth_yoy AS revenue_growth,
                annual_operating_income_growth_yoy AS operating_income_growth
            FROM {annual_relation}
        )
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE quarterly_periods AS
        SELECT
            CAST(gvkey AS VARCHAR) AS gvkey,
            CAST(datadate AS DATE) AS datadate,
            fyearq,
            fqtr,
            fyearq * 4 + fqtr AS fiscal_quarter_index,
            ticker,
            company_name,
            quarterly_revenue_growth_yoy AS revenue_growth,
            quarterly_operating_income_growth_yoy AS operating_income_growth
        FROM {quarterly_relation}
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE annual_ranked AS
        SELECT
            q.evaluation_date,
            a.*,
            ROW_NUMBER() OVER (
                PARTITION BY q.evaluation_date, a.gvkey
                ORDER BY a.datadate DESC, a.fyear DESC
            ) AS period_rank
        FROM evaluation_quarters q
        JOIN annual_periods a ON a.datadate <= q.evaluation_date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE quarterly_ranked AS
        SELECT
            q.evaluation_date,
            f.*,
            ROW_NUMBER() OVER (
                PARTITION BY q.evaluation_date, f.gvkey
                ORDER BY f.datadate DESC, f.fyearq DESC, f.fqtr DESC
            ) AS period_rank
        FROM evaluation_quarters q
        JOIN quarterly_periods f ON f.datadate <= q.evaluation_date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE annual_evaluation AS
        SELECT
            r.evaluation_date,
            r.gvkey,
            p.annual_growth_pct,
            p.annual_years,
            arg_max(r.ticker, r.datadate) AS ticker,
            arg_max(r.company_name, r.datadate) AS company_name,
            string_agg(CAST(r.datadate AS VARCHAR), ', ' ORDER BY r.datadate DESC)
                AS annual_period_dates,
            bool_and(
                r.previous_available_fyear = r.fyear - 1
                AND r.revenue_growth IS NOT NULL
                AND r.operating_income_growth IS NOT NULL
                AND r.revenue_growth >= p.annual_growth_pct / 100.0
                AND r.operating_income_growth >= p.annual_growth_pct / 100.0
            ) AS flag_a
        FROM annual_ranked r
        JOIN (
            SELECT DISTINCT annual_growth_pct, annual_years
            FROM ab_parameter_grid
        ) p ON r.period_rank <= p.annual_years
        GROUP BY r.evaluation_date, r.gvkey, p.annual_growth_pct, p.annual_years
        HAVING COUNT(*) = p.annual_years
           AND COUNT(DISTINCT r.fyear) = p.annual_years
           AND MAX(r.fyear) - MIN(r.fyear) = p.annual_years - 1
           AND COUNT(*) FILTER (
               WHERE r.previous_available_fyear = r.fyear - 1
                 AND r.revenue_growth IS NOT NULL
                 AND r.operating_income_growth IS NOT NULL
           ) = p.annual_years
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE quarterly_evaluation AS
        SELECT
            r.evaluation_date,
            r.gvkey,
            p.quarterly_growth_pct,
            p.quarter_count,
            arg_max(r.ticker, r.datadate) AS ticker,
            arg_max(r.company_name, r.datadate) AS company_name,
            string_agg(CAST(r.datadate AS VARCHAR), ', ' ORDER BY r.datadate DESC)
                AS quarterly_period_dates,
            bool_and(
                r.revenue_growth IS NOT NULL
                AND r.operating_income_growth IS NOT NULL
                AND r.revenue_growth >= p.quarterly_growth_pct / 100.0
                AND r.operating_income_growth >= p.quarterly_growth_pct / 100.0
            ) AS flag_b
        FROM quarterly_ranked r
        JOIN (
            SELECT DISTINCT quarterly_growth_pct, quarter_count
            FROM ab_parameter_grid
        ) p ON r.period_rank <= p.quarter_count
        GROUP BY r.evaluation_date, r.gvkey, p.quarterly_growth_pct, p.quarter_count
        HAVING COUNT(*) = p.quarter_count
           AND COUNT(DISTINCT r.fiscal_quarter_index) = p.quarter_count
           AND MAX(r.fiscal_quarter_index) - MIN(r.fiscal_quarter_index)
               = p.quarter_count - 1
           AND COUNT(*) FILTER (
               WHERE r.revenue_growth IS NOT NULL
                 AND r.operating_income_growth IS NOT NULL
           ) = p.quarter_count
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ab_company_evaluation AS
        SELECT
            p.parameter_id,
            p.parameter_name,
            p.annual_growth_pct,
            p.annual_years,
            p.quarterly_growth_pct,
            p.quarter_count,
            a.evaluation_date,
            a.gvkey,
            COALESCE(a.ticker, b.ticker) AS ticker,
            COALESCE(a.company_name, b.company_name) AS company_name,
            a.annual_period_dates,
            b.quarterly_period_dates,
            a.flag_a,
            b.flag_b,
            a.flag_a AND b.flag_b AS passed_ab
        FROM ab_parameter_grid p
        JOIN annual_evaluation a
          ON a.annual_growth_pct = p.annual_growth_pct
         AND a.annual_years = p.annual_years
        JOIN quarterly_evaluation b
          ON b.evaluation_date = a.evaluation_date
         AND b.gvkey = a.gvkey
         AND b.quarterly_growth_pct = p.quarterly_growth_pct
         AND b.quarter_count = p.quarter_count
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ab_quarterly_coverage AS
        SELECT
            parameter_id,
            parameter_name,
            annual_growth_pct,
            annual_years,
            quarterly_growth_pct,
            quarter_count,
            evaluation_date,
            COUNT(DISTINCT gvkey) AS eligible_company_count,
            COUNT(DISTINCT gvkey) FILTER (WHERE flag_a) AS condition_a_count,
            COUNT(DISTINCT gvkey) FILTER (WHERE flag_b) AS condition_b_count,
            COUNT(DISTINCT gvkey) FILTER (WHERE passed_ab) AS selected_company_count
        FROM ab_company_evaluation
        GROUP BY ALL
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE ab_parameter_window_bounds AS
        SELECT
            parameter_id,
            MIN(evaluation_date) AS first_included_quarter
        FROM ab_quarterly_coverage
        GROUP BY parameter_id
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE ab_common_window_summary AS
        WITH common_window AS (
            SELECT MAX(first_included_quarter) AS common_start_quarter
            FROM ab_parameter_window_bounds
        )
        SELECT
            q.parameter_id,
            q.parameter_name,
            q.annual_growth_pct,
            q.annual_years,
            q.quarterly_growth_pct,
            q.quarter_count,
            MIN(q.evaluation_date) AS common_start_quarter,
            MAX(q.evaluation_date) AS common_end_quarter,
            COUNT(*) AS included_quarter_count,
            AVG(q.selected_company_count) AS average_selected_company_count,
            ABS(AVG(q.selected_company_count) - {TARGET_COMPANY_COUNT})
                AS distance_from_target_30,
            COUNT(*) FILTER (WHERE q.selected_company_count = {TARGET_COMPANY_COUNT})
                AS quarters_selecting_exactly_30,
            DENSE_RANK() OVER (
                ORDER BY ABS(AVG(q.selected_company_count) - {TARGET_COMPANY_COUNT}),
                         q.parameter_id
            ) AS common_window_coverage_rank
        FROM ab_quarterly_coverage q
        CROSS JOIN common_window w
        WHERE q.evaluation_date >= w.common_start_quarter
        GROUP BY
            q.parameter_id, q.parameter_name, q.annual_growth_pct, q.annual_years,
            q.quarterly_growth_pct, q.quarter_count
        """
    )


def write_outputs(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "ab_parameter_grid": "SELECT * FROM ab_parameter_grid ORDER BY parameter_id",
        "ab_quarterly_coverage": (
            "SELECT * FROM ab_quarterly_coverage ORDER BY parameter_id, evaluation_date"
        ),
        "ab_common_window_summary": (
            "SELECT * FROM ab_common_window_summary "
            "ORDER BY common_window_coverage_rank, parameter_id"
        ),
        "ab_selections": (
            "SELECT * FROM ab_company_evaluation WHERE passed_ab "
            "ORDER BY parameter_id, evaluation_date, gvkey"
        ),
    }
    for name, query in outputs.items():
        relation = con.sql(query)
        relation.write_parquet(str(output_dir / f"{name}.parquet"), compression="zstd")
        if name != "ab_selections":
            relation.write_csv(str(output_dir / f"{name}.csv"), header=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run A&B quarterly coverage analysis.")
    parser.add_argument("--start-date", default=str(DEFAULT_START_DATE))
    parser.add_argument("--end-date", default=str(DEFAULT_END_DATE))
    parser.add_argument("--output-dir", type=Path, default=RESULT_DIR / "ab_coverage")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_date = date.fromisoformat(args.start_date)
    end_date = date.fromisoformat(args.end_date)
    if start_date > end_date:
        raise RuntimeError("Start date must be on or before end date.")

    con = connect_duckdb_with_s3()
    con.execute("PRAGMA threads=4")
    create_ab_coverage_tables(con, start_date, end_date)
    write_outputs(con, args.output_dir)

    print(f"A&B coverage outputs: {args.output_dir.resolve()}")
    print(
        con.sql(
            """
            SELECT
                common_window_coverage_rank,
                parameter_name,
                ROUND(average_selected_company_count, 2) AS average_selected,
                ROUND(distance_from_target_30, 2) AS distance_from_30,
                included_quarter_count,
                quarters_selecting_exactly_30
            FROM ab_common_window_summary
            ORDER BY common_window_coverage_rank, parameter_id
            LIMIT 15
            """
        ).df().to_string(index=False)
    )


if __name__ == "__main__":
    main()

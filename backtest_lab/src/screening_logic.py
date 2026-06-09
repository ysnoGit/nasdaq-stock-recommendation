from __future__ import annotations

from pathlib import Path

import duckdb

from backtest_lab.src.config import (
    ANNUAL_GROWTH_S3_PATH,
    DAILY_FEATURE_PATH,
    QUARTERLY_GROWTH_S3_PATH,
    WEEKLY_FEATURE_PATH,
)
from server_pipeline.s3_duckdb import connect_duckdb_with_s3


SELECTION_COLUMNS = [
    "parameter_set_id", "screen_type", "selected_date", "gvkey", "iid", "ticker",
    "company_name", "selected_price", "selected_adjusted_price", "flag_a", "flag_b",
    "flag_c", "flag_d", "flag_e", "flag_f", "flag_g", "flag_h",
]


def path_sql(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def create_screening_connection() -> duckdb.DuckDBPyConnection:
    con = connect_duckdb_with_s3()
    con.execute("PRAGMA threads=4")
    con.execute(
        f"CREATE TEMP VIEW daily AS SELECT * FROM read_parquet('{path_sql(DAILY_FEATURE_PATH)}')"
    )
    con.execute(
        f"CREATE TEMP VIEW weekly AS SELECT * FROM read_parquet('{path_sql(WEEKLY_FEATURE_PATH)}')"
    )
    con.execute(
        f"""
        CREATE TEMP TABLE annual AS
        SELECT
            CAST(gvkey AS VARCHAR) AS gvkey,
            CAST(datadate AS DATE) AS datadate,
            annual_revenue_growth_yoy AS annual_revenue_growth,
            annual_operating_income_growth_yoy AS annual_operating_income_growth
        FROM read_parquet('{ANNUAL_GROWTH_S3_PATH}')
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE quarterly AS
        SELECT
            CAST(gvkey AS VARCHAR) AS gvkey,
            CAST(datadate AS DATE) AS datadate,
            quarterly_revenue_growth_yoy AS quarterly_revenue_growth,
            quarterly_operating_income_growth_yoy AS quarterly_operating_income_growth
        FROM read_parquet('{QUARTERLY_GROWTH_S3_PATH}')
        """
    )
    con.execute("CREATE INDEX annual_security_date_idx ON annual(gvkey, datadate)")
    con.execute("CREATE INDEX quarterly_security_date_idx ON quarterly(gvkey, datadate)")
    return con


def evaluate_parameter(con: duckdb.DuckDBPyConnection, parameter: dict) -> duckdb.DuckDBPyRelation:
    p = parameter
    end_filter = ""
    if p.get("end_date") is not None:
        end_filter = f"AND d.snapshot_date <= DATE '{p['end_date']}'"
    annual_threshold = float(p["annual_growth_pct"]) / 100.0
    quarterly_threshold = float(p["quarterly_growth_pct"]) / 100.0
    daily_tol = float(p["daily_ma_tolerance_pct"]) / 100.0
    weekly_tol = float(p["weekly_ma_tolerance_pct"]) / 100.0

    query = f"""
    WITH volume_history AS (
        SELECT
            *,
            COUNT(*) FILTER (WHERE volume_ratio >= {float(p["volume_ratio_threshold"])}) OVER (
                PARTITION BY gvkey, iid
                ORDER BY snapshot_date
                RANGE BETWEEN INTERVAL 3 MONTH PRECEDING AND CURRENT ROW
            ) AS surge_days
        FROM daily
    ),
    technical_candidates AS (
        SELECT *
        FROM volume_history d
        WHERE d.snapshot_date >= DATE '{p["start_date"]}'
          {end_filter}
          AND d.volume_ratio >= {float(p["volume_ratio_threshold"])}
          AND d.surge_days >= {int(p["volume_surge_min_days"])}
          AND d.ma20 IS NOT NULL AND d.ma50 IS NOT NULL AND d.ma100 IS NOT NULL
          AND d.ma50 <> 0 AND d.ma100 <> 0
          AND d.ma20 / d.ma50 BETWEEN {1 - daily_tol} AND {1 + daily_tol}
          AND d.ma50 / d.ma100 BETWEEN {1 - daily_tol} AND {1 + daily_tol}
          AND d.ma20 / d.ma100 BETWEEN {1 - daily_tol} AND {1 + daily_tol}
          AND d.future_daily_ma20 IS NOT NULL
          AND d.future_daily_ma50 IS NOT NULL
          AND d.future_daily_ma100 IS NOT NULL
          AND d.future_daily_ma50 <> 0 AND d.future_daily_ma100 <> 0
          AND d.future_daily_ma20 / d.future_daily_ma50 BETWEEN {1 - daily_tol} AND {1 + daily_tol}
          AND d.future_daily_ma50 / d.future_daily_ma100 BETWEEN {1 - daily_tol} AND {1 + daily_tol}
          AND d.future_daily_ma20 / d.future_daily_ma100 BETWEEN {1 - daily_tol} AND {1 + daily_tol}
    ),
    fundamental_candidates AS (
        SELECT d.*
        FROM technical_candidates d
        JOIN LATERAL (
            SELECT
                COUNT(*) AS valid_count,
                COUNT(*) FILTER (
                    WHERE annual_revenue_growth >= {annual_threshold}
                      AND annual_operating_income_growth >= {annual_threshold}
                ) AS pass_count
            FROM (
                SELECT annual_revenue_growth, annual_operating_income_growth
                FROM annual a
                WHERE a.gvkey = d.gvkey
                  AND a.datadate <= d.snapshot_date
                  AND a.annual_revenue_growth IS NOT NULL
                  AND a.annual_operating_income_growth IS NOT NULL
                ORDER BY a.datadate DESC
                LIMIT {int(p["annual_years"])}
            )
        ) a ON true
        JOIN LATERAL (
            SELECT
                COUNT(*) AS valid_count,
                COUNT(*) FILTER (
                    WHERE quarterly_revenue_growth >= {quarterly_threshold}
                      AND quarterly_operating_income_growth >= {quarterly_threshold}
                ) AS pass_count
            FROM (
                SELECT quarterly_revenue_growth, quarterly_operating_income_growth
                FROM quarterly q
                WHERE q.gvkey = d.gvkey
                  AND q.datadate <= d.snapshot_date
                  AND q.quarterly_revenue_growth IS NOT NULL
                  AND q.quarterly_operating_income_growth IS NOT NULL
                ORDER BY q.datadate DESC
                LIMIT {int(p["quarter_count"])}
            )
        ) q ON true
        WHERE a.valid_count = {int(p["annual_years"])}
          AND a.pass_count = {int(p["annual_years"])}
          AND q.valid_count = {int(p["quarter_count"])}
          AND q.pass_count = {int(p["quarter_count"])}
    ),
    af AS (
        SELECT
            {int(p["parameter_set_id"])} AS parameter_set_id,
            'A_F' AS screen_type,
            snapshot_date AS selected_date,
            gvkey, iid, ticker, company_name,
            COALESCE(adjusted_close_price, close_price) AS selected_price,
            adjusted_close_price AS selected_adjusted_price,
            TRUE AS flag_a, TRUE AS flag_b, TRUE AS flag_c, TRUE AS flag_d,
            TRUE AS flag_e, TRUE AS flag_f,
            NULL::BOOLEAN AS flag_g, NULL::BOOLEAN AS flag_h,
            ROW_NUMBER() OVER (PARTITION BY gvkey, iid ORDER BY snapshot_date) AS rn
        FROM fundamental_candidates
    ),
    ah AS (
        SELECT
            {int(p["parameter_set_id"])} AS parameter_set_id,
            'A_H' AS screen_type,
            d.snapshot_date AS selected_date,
            d.gvkey, d.iid, d.ticker, d.company_name,
            COALESCE(d.adjusted_close_price, d.close_price) AS selected_price,
            d.adjusted_close_price AS selected_adjusted_price,
            TRUE AS flag_a, TRUE AS flag_b, TRUE AS flag_c, TRUE AS flag_d,
            TRUE AS flag_e, TRUE AS flag_f, TRUE AS flag_g, TRUE AS flag_h,
            ROW_NUMBER() OVER (PARTITION BY d.gvkey, d.iid ORDER BY d.snapshot_date) AS rn
        FROM fundamental_candidates d
        JOIN weekly w
          ON w.week_end_date = d.snapshot_date
         AND w.gvkey = d.gvkey
         AND w.iid = d.iid
        WHERE w.weekly_ma5 IS NOT NULL AND w.weekly_ma10 IS NOT NULL AND w.weekly_ma30 IS NOT NULL
          AND w.weekly_ma10 <> 0 AND w.weekly_ma30 <> 0
          AND w.weekly_ma5 / w.weekly_ma10 BETWEEN {1 - weekly_tol} AND {1 + weekly_tol}
          AND w.weekly_ma10 / w.weekly_ma30 BETWEEN {1 - weekly_tol} AND {1 + weekly_tol}
          AND w.weekly_ma5 / w.weekly_ma30 BETWEEN {1 - weekly_tol} AND {1 + weekly_tol}
          AND w.future_weekly_ma5 IS NOT NULL
          AND w.future_weekly_ma10 IS NOT NULL
          AND w.future_weekly_ma30 IS NOT NULL
          AND w.future_weekly_ma10 <> 0 AND w.future_weekly_ma30 <> 0
          AND w.future_weekly_ma5 / w.future_weekly_ma10 BETWEEN {1 - weekly_tol} AND {1 + weekly_tol}
          AND w.future_weekly_ma10 / w.future_weekly_ma30 BETWEEN {1 - weekly_tol} AND {1 + weekly_tol}
          AND w.future_weekly_ma5 / w.future_weekly_ma30 BETWEEN {1 - weekly_tol} AND {1 + weekly_tol}
    )
    SELECT {", ".join(SELECTION_COLUMNS)} FROM af WHERE rn = 1
    UNION ALL
    SELECT {", ".join(SELECTION_COLUMNS)} FROM ah WHERE rn = 1
    """
    return con.sql(query)

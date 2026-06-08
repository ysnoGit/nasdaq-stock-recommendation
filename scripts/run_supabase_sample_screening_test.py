from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[1]))

from server_pipeline.utils.trading_calendar import official_week_end_trading_date  # noqa: E402


def require_supabase_db_url() -> str:
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL is not set. Run:\n"
            'export SUPABASE_DB_URL="postgresql://..."'
        )
    return db_url


def connect_supabase():
    db_url = require_supabase_db_url()
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is not installed. Run: python3 -m pip install 'psycopg[binary]'"
        ) from exc

    return psycopg.connect(db_url)


def scalar(cur, sql: str, params: dict[str, Any] | None = None) -> Any:
    cur.execute(sql, params or {})
    return cur.fetchone()[0]


def table_exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (table,))
    return cur.fetchone()[0] is not None


def require_tables(cur, tables: list[str]) -> None:
    missing = [table for table in tables if not table_exists(cur, table)]
    if missing:
        raise RuntimeError(
            "Missing Supabase serving table(s): "
            f"{', '.join(missing)}. Run:\n"
            "bash scripts/load_processed_features_to_supabase.sh --apply-schema"
        )


def validate_confirmation_fields(cur) -> None:
    checks = [
        (
            "daily_duplicate_keys",
            """
            SELECT COUNT(*)
            FROM (
                SELECT snapshot_date, gvkey, iid
                FROM security_daily_feature_snapshot
                GROUP BY snapshot_date, gvkey, iid
                HAVING COUNT(*) > 1
            ) AS dupes
            """,
        ),
        (
            "weekly_duplicate_keys",
            """
            SELECT COUNT(*)
            FROM (
                SELECT week_end_date, gvkey, iid
                FROM security_weekly_feature_snapshot
                GROUP BY week_end_date, gvkey, iid
                HAVING COUNT(*) > 1
            ) AS dupes
            """,
        ),
        (
            "bad_daily_future_date_rows",
            """
            SELECT COUNT(*)
            FROM security_daily_feature_snapshot
            WHERE daily_f_confirmed_using_date IS NOT NULL
              AND daily_f_confirmed_using_date <= snapshot_date
            """,
        ),
        (
            "bad_weekly_future_date_rows",
            """
            SELECT COUNT(*)
            FROM security_weekly_feature_snapshot
            WHERE weekly_h_confirmed_using_date IS NOT NULL
              AND weekly_h_confirmed_using_date <= week_end_date
            """,
        ),
        (
            "bad_daily_null_rows",
            """
            SELECT COUNT(*)
            FROM security_daily_feature_snapshot
            WHERE daily_f_confirmed_using_date IS NULL
              AND (
                  future_daily_ma20 IS NOT NULL
                  OR future_daily_ma50 IS NOT NULL
                  OR future_daily_ma100 IS NOT NULL
              )
            """,
        ),
        (
            "bad_weekly_null_rows",
            """
            SELECT COUNT(*)
            FROM security_weekly_feature_snapshot
            WHERE weekly_h_confirmed_using_date IS NULL
              AND (
                  future_weekly_ma5 IS NOT NULL
                  OR future_weekly_ma10 IS NOT NULL
                  OR future_weekly_ma30 IS NOT NULL
              )
            """,
        ),
    ]

    failures = {}
    print("\nFuture F/H input validation:")
    for label, sql in checks:
        count = int(scalar(cur, sql))
        print(f"{label}: {count:,}")
        if count:
            failures[label] = count

    if failures:
        formatted = ", ".join(f"{label}={count:,}" for label, count in failures.items())
        raise RuntimeError(f"Future F/H input validation failed: {formatted}")

    cur.execute("""
        SELECT DISTINCT week_start_date, week_end_date
        FROM security_weekly_feature_snapshot
        ORDER BY week_start_date
    """)
    bad_week_ends = []
    for week_start_date, week_end_date in cur.fetchall():
        official_end = official_week_end_trading_date(week_start_date)
        if official_end != week_end_date:
            bad_week_ends.append((week_start_date, week_end_date, official_end))

    print(f"official_week_end_validation_rows: {len(bad_week_ends):,}")
    if bad_week_ends:
        preview = bad_week_ends[:10]
        raise RuntimeError(
            "Weekly serving rows contain non-official week_end_date values: "
            f"{preview}"
        )

    missing_future_links = int(scalar(cur, """
        SELECT COUNT(*)
        FROM security_weekly_feature_snapshot AS w
        WHERE w.weekly_h_confirmed_using_date IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM security_weekly_feature_snapshot AS future_w
              WHERE future_w.gvkey = w.gvkey
                AND future_w.iid = w.iid
                AND future_w.week_end_date = w.weekly_h_confirmed_using_date
          )
    """))
    print(f"weekly_h_missing_future_link_rows: {missing_future_links:,}")
    if missing_future_links:
        raise RuntimeError(
            "weekly_h_confirmed_using_date does not point to a future weekly row "
            "for the same gvkey/iid."
        )


def run_sample_query(cur, label: str, params: dict[str, Any], include_weekly: bool) -> None:
    weekly_select = """
        CASE
            WHEN w.weekly_ma5 IS NULL
              OR w.weekly_ma10 IS NULL
              OR w.weekly_ma30 IS NULL
            THEN NULL
            WHEN w.weekly_ma10 = 0
              OR w.weekly_ma30 = 0
            THEN FALSE
            ELSE (
                w.weekly_ma5 / w.weekly_ma10
                    BETWEEN %(weekly_ma_lower_bound)s AND %(weekly_ma_upper_bound)s
                AND w.weekly_ma10 / w.weekly_ma30
                    BETWEEN %(weekly_ma_lower_bound)s AND %(weekly_ma_upper_bound)s
                AND w.weekly_ma5 / w.weekly_ma30
                    BETWEEN %(weekly_ma_lower_bound)s AND %(weekly_ma_upper_bound)s
            )
        END AS flag_g,
        CASE
            WHEN w.weekly_h_confirmed_using_date IS NULL
              OR w.future_weekly_ma5 IS NULL
              OR w.future_weekly_ma10 IS NULL
              OR w.future_weekly_ma30 IS NULL
            THEN NULL
            WHEN w.future_weekly_ma10 = 0
              OR w.future_weekly_ma30 = 0
            THEN FALSE
            ELSE (
                w.future_weekly_ma5 / w.future_weekly_ma10
                    BETWEEN %(weekly_ma_lower_bound)s AND %(weekly_ma_upper_bound)s
                AND w.future_weekly_ma10 / w.future_weekly_ma30
                    BETWEEN %(weekly_ma_lower_bound)s AND %(weekly_ma_upper_bound)s
                AND w.future_weekly_ma5 / w.future_weekly_ma30
                    BETWEEN %(weekly_ma_lower_bound)s AND %(weekly_ma_upper_bound)s
            )
        END AS flag_h,
        w.weekly_h_confirmed_using_date,
    """ if include_weekly else """
        NULL::boolean AS flag_g,
        NULL::boolean AS flag_h,
        NULL::date AS weekly_h_confirmed_using_date,
    """
    weekly_join = """
    JOIN security_weekly_feature_snapshot AS w
      ON d.snapshot_date = w.week_end_date
     AND d.gvkey = w.gvkey
     AND d.iid = w.iid
    """ if include_weekly else ""

    query = """
    WITH selected_snapshot AS (
        SELECT COALESCE(%(selected_date)s::date, MAX(snapshot_date)) AS selected_date
        FROM security_daily_feature_snapshot
    ),

    latest_daily AS (
        SELECT s.*
        FROM security_daily_feature_snapshot AS s
        JOIN selected_snapshot AS ss
          ON s.snapshot_date = ss.selected_date
    ),

    annual_flags AS (
        SELECT
            gvkey,
            COUNT(*) FILTER (
                WHERE annual_rank_desc <= %(annual_years)s
                  AND annual_revenue_growth >= %(annual_growth_pct)s
                  AND annual_operating_income_growth >= %(annual_growth_pct)s
            ) AS annual_pass_count
        FROM annual_growth_history
        WHERE annual_rank_desc <= %(annual_years)s
        GROUP BY gvkey
    ),

    quarterly_flags AS (
        SELECT
            gvkey,
            COUNT(*) FILTER (
                WHERE quarterly_rank_desc <= %(quarter_count)s
                  AND quarterly_revenue_growth >= %(quarterly_growth_pct)s
                  AND quarterly_operating_income_growth >= %(quarterly_growth_pct)s
            ) AS quarterly_pass_count
        FROM quarterly_growth_history
        WHERE quarterly_rank_desc <= %(quarter_count)s
        GROUP BY gvkey
    ),

    recent_volume AS (
        SELECT
            s.gvkey,
            s.iid,
            COUNT(*) FILTER (WHERE s.volume_ratio >= %(q)s) AS recent_c_count
        FROM security_daily_feature_snapshot AS s
        CROSS JOIN selected_snapshot AS ss
        WHERE s.snapshot_date BETWEEN ss.selected_date - INTERVAL '3 months'
                                  AND ss.selected_date
        GROUP BY s.gvkey, s.iid
    )

    SELECT
        d.snapshot_date,
        sm.ticker,
        sm.company_name,
        d.gvkey,
        d.iid,
        d.volume_ratio,
        rv.recent_c_count,
        COALESCE(af.annual_pass_count, 0) >= %(annual_years)s AS flag_a,
        COALESCE(qf.quarterly_pass_count, 0) >= %(quarter_count)s AS flag_b,
        d.volume_ratio >= %(q)s AS flag_c,
        COALESCE(rv.recent_c_count, 0) >= %(m)s AS flag_d,
        CASE
            WHEN d.ma20 IS NULL
              OR d.ma50 IS NULL
              OR d.ma100 IS NULL
            THEN NULL
            WHEN d.ma50 = 0
              OR d.ma100 = 0
            THEN FALSE
            ELSE (
                d.ma20 / d.ma50 BETWEEN %(daily_ma_lower_bound)s AND %(daily_ma_upper_bound)s
                AND d.ma50 / d.ma100 BETWEEN %(daily_ma_lower_bound)s AND %(daily_ma_upper_bound)s
                AND d.ma20 / d.ma100 BETWEEN %(daily_ma_lower_bound)s AND %(daily_ma_upper_bound)s
            )
        END AS flag_e,
        CASE
            WHEN d.daily_f_confirmed_using_date IS NULL
              OR d.future_daily_ma20 IS NULL
              OR d.future_daily_ma50 IS NULL
              OR d.future_daily_ma100 IS NULL
            THEN NULL
            WHEN d.future_daily_ma50 = 0
              OR d.future_daily_ma100 = 0
            THEN FALSE
            ELSE (
                d.future_daily_ma20 / d.future_daily_ma50
                    BETWEEN %(daily_ma_lower_bound)s AND %(daily_ma_upper_bound)s
                AND d.future_daily_ma50 / d.future_daily_ma100
                    BETWEEN %(daily_ma_lower_bound)s AND %(daily_ma_upper_bound)s
                AND d.future_daily_ma20 / d.future_daily_ma100
                    BETWEEN %(daily_ma_lower_bound)s AND %(daily_ma_upper_bound)s
            )
        END AS flag_f,
        d.daily_f_confirmed_using_date,
        {weekly_select}
        sm.is_excluded_universe,
        sm.exclusion_reason
    FROM latest_daily AS d
    {weekly_join}
    JOIN security_master AS sm
      ON d.gvkey = sm.gvkey
     AND d.iid = sm.iid
    LEFT JOIN annual_flags AS af
      ON d.gvkey = af.gvkey
    LEFT JOIN quarterly_flags AS qf
      ON d.gvkey = qf.gvkey
    LEFT JOIN recent_volume AS rv
      ON d.gvkey = rv.gvkey
     AND d.iid = rv.iid
    WHERE (%(universe_filter)s = false OR sm.is_excluded_universe = false)
    ORDER BY
        flag_a DESC,
        flag_b DESC,
        flag_d DESC,
        d.volume_ratio DESC NULLS LAST
    LIMIT 10
    """.format(weekly_select=weekly_select, weekly_join=weekly_join)
    cur.execute(query, params)
    rows = cur.fetchall()
    columns = [desc.name if hasattr(desc, "name") else desc[0] for desc in cur.description]

    print(f"\n{label} sample rows: {len(rows):,}")
    print(", ".join(columns))
    for row in rows:
        print(row)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Supabase serving tables and run sample dynamic screening queries."
    )
    parser.parse_args()

    print("Running Supabase sample screening validation.")
    print("SUPABASE_DB_URL: set" if os.environ.get("SUPABASE_DB_URL") else "SUPABASE_DB_URL: missing")

    with connect_supabase() as conn:
        with conn.cursor() as cur:
            tables = [
                "security_master",
                "security_daily_feature_snapshot",
                "security_weekly_feature_snapshot",
                "annual_growth_history",
                "quarterly_growth_history",
            ]
            require_tables(cur, tables)
            for table in tables:
                count = scalar(cur, f"SELECT COUNT(*) FROM {table}")
                print(f"{table}: {count:,} rows")

            latest_snapshot_date = scalar(cur, "SELECT MAX(snapshot_date) FROM security_daily_feature_snapshot")
            print(f"Latest snapshot date: {latest_snapshot_date}")
            if latest_snapshot_date is None:
                raise RuntimeError("security_daily_feature_snapshot has no rows.")

            latest_completed_week_date = scalar(cur, """
                SELECT MAX(w.week_end_date)
                FROM security_weekly_feature_snapshot AS w
                WHERE EXISTS (
                    SELECT 1
                    FROM security_daily_feature_snapshot AS d
                    WHERE d.snapshot_date = w.week_end_date
                      AND d.gvkey = w.gvkey
                      AND d.iid = w.iid
                )
            """)
            print(f"Latest completed weekly screening date: {latest_completed_week_date}")
            if latest_completed_week_date is None:
                raise RuntimeError("No completed weekly date joins to daily serving rows.")

            cur.execute("""
                SELECT
                    COUNT(*) AS latest_rows,
                    COUNT(sm.gvkey) AS joined_master_rows
                FROM security_daily_feature_snapshot AS s
                LEFT JOIN security_master AS sm
                  ON s.gvkey = sm.gvkey
                 AND s.iid = sm.iid
                WHERE s.snapshot_date = %(latest_snapshot_date)s
            """, {"latest_snapshot_date": latest_snapshot_date})
            latest_rows, joined_master_rows = cur.fetchone()
            print(f"Latest snapshot master join: {joined_master_rows:,}/{latest_rows:,}")
            if joined_master_rows < latest_rows:
                raise RuntimeError("Latest snapshot rows do not all join to security_master.")

            validate_confirmation_fields(cur)

            dynamic_d_count = scalar(cur, """
                WITH recent_volume AS (
                    SELECT
                        gvkey,
                        iid,
                        COUNT(*) FILTER (WHERE volume_ratio >= %(q)s) AS recent_c_count
                    FROM security_daily_feature_snapshot
                    WHERE snapshot_date BETWEEN (%(selected_date)s::date - INTERVAL '3 months')
                                            AND %(selected_date)s::date
                    GROUP BY gvkey, iid
                )
                SELECT COUNT(*)
                FROM recent_volume
                WHERE recent_c_count >= %(m)s
            """, {"q": 5, "m": 3, "selected_date": latest_snapshot_date})
            print(f"Dynamic Condition D pass count for q=5, m=3: {dynamic_d_count:,}")

            run_sample_query(
                cur,
                "Strict A-F latest daily: growth=10%, annual=3, quarterly=4, daily_tol=2%, q=5, m=3",
                {
                    "selected_date": latest_snapshot_date,
                    "annual_growth_pct": 0.10,
                    "quarterly_growth_pct": 0.10,
                    "annual_years": 3,
                    "quarter_count": 4,
                    "daily_ma_lower_bound": 0.98,
                    "daily_ma_upper_bound": 1.02,
                    "weekly_ma_lower_bound": 0.98,
                    "weekly_ma_upper_bound": 1.02,
                    "q": 5,
                    "m": 3,
                    "universe_filter": True,
                },
                False,
            )
            run_sample_query(
                cur,
                "Relaxed A-H latest weekly: growth=5%, annual=2, quarterly=2, daily_tol=5%, weekly_tol=5%, q=3, m=2",
                {
                    "selected_date": latest_completed_week_date,
                    "annual_growth_pct": 0.05,
                    "quarterly_growth_pct": 0.05,
                    "annual_years": 2,
                    "quarter_count": 2,
                    "daily_ma_lower_bound": 0.95,
                    "daily_ma_upper_bound": 1.05,
                    "weekly_ma_lower_bound": 0.95,
                    "weekly_ma_upper_bound": 1.05,
                    "q": 3,
                    "m": 2,
                    "universe_filter": True,
                },
                True,
            )


if __name__ == "__main__":
    main()

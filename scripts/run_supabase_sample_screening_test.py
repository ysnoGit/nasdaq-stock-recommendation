from __future__ import annotations

import argparse
import os
from typing import Any


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
            "bad_f_rows",
            """
            SELECT COUNT(*)
            FROM security_feature_snapshot
            WHERE daily_f_confirmed_using_date IS NOT NULL
              AND daily_f_confirmed_using_date <= snapshot_date
            """,
        ),
        (
            "bad_h_rows",
            """
            SELECT COUNT(*)
            FROM security_feature_snapshot
            WHERE weekly_h_confirmed_using_date IS NOT NULL
              AND weekly_h_confirmed_using_date <= snapshot_date
            """,
        ),
        (
            "bad_f_null_consistency_rows",
            """
            SELECT COUNT(*)
            FROM security_feature_snapshot
            WHERE daily_f_confirmed_using_date IS NULL
              AND daily_f_confirmation_pass IS NOT NULL
            """,
        ),
        (
            "bad_h_null_consistency_rows",
            """
            SELECT COUNT(*)
            FROM security_feature_snapshot
            WHERE weekly_h_confirmed_using_date IS NULL
              AND weekly_h_confirmation_pass IS NOT NULL
            """,
        ),
        (
            "bad_f_evaluated_consistency_rows",
            """
            SELECT COUNT(*)
            FROM security_feature_snapshot
            WHERE daily_f_confirmed_using_date IS NOT NULL
              AND daily_f_confirmation_pass IS NULL
            """,
        ),
        (
            "bad_h_evaluated_consistency_rows",
            """
            SELECT COUNT(*)
            FROM security_feature_snapshot
            WHERE weekly_h_confirmed_using_date IS NOT NULL
              AND weekly_h_confirmation_pass IS NULL
            """,
        ),
    ]

    failures = {}
    print("\nF/H confirmation validation:")
    for label, sql in checks:
        count = int(scalar(cur, sql))
        print(f"{label}: {count:,}")
        if count:
            failures[label] = count

    if failures:
        formatted = ", ".join(f"{label}={count:,}" for label, count in failures.items())
        raise RuntimeError(f"F/H confirmation validation failed: {formatted}")


def run_sample_query(cur, label: str, params: dict[str, Any]) -> None:
    query = """
    WITH selected_snapshot AS (
        SELECT COALESCE(%(selected_date)s::date, MAX(snapshot_date)) AS selected_date
        FROM security_feature_snapshot
    ),

    latest_daily AS (
        SELECT s.*
        FROM security_feature_snapshot AS s
        JOIN selected_snapshot AS ss
          ON s.snapshot_date = ss.selected_date
    ),

    annual_flags AS (
        SELECT
            gvkey,
            COUNT(*) FILTER (
                WHERE annual_rank_desc <= %(annual_years)s
                  AND annual_revenue_growth >= %(n_pct)s
                  AND annual_operating_income_growth >= %(n_pct)s
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
                  AND quarterly_revenue_growth >= %(n_pct)s
                  AND quarterly_operating_income_growth >= %(n_pct)s
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
        FROM security_feature_snapshot AS s
        CROSS JOIN selected_snapshot AS ss
        WHERE s.snapshot_date BETWEEN ss.selected_date - INTERVAL '3 months'
                                  AND ss.selected_date
        GROUP BY s.gvkey, s.iid
    )

    SELECT
        ld.snapshot_date,
        sm.ticker,
        sm.company_name,
        ld.gvkey,
        ld.iid,
        ld.volume_ratio,
        rv.recent_c_count,
        COALESCE(af.annual_pass_count, 0) >= %(annual_years)s AS flag_a,
        COALESCE(qf.quarterly_pass_count, 0) >= %(quarter_count)s AS flag_b,
        ld.volume_ratio >= %(q)s AS flag_c,
        COALESCE(rv.recent_c_count, 0) >= %(m)s AS flag_d,
        ld.daily_f_confirmation_pass AS flag_f,
        ld.weekly_h_confirmation_pass AS flag_h,
        sm.is_excluded_universe,
        sm.exclusion_reason
    FROM latest_daily AS ld
    JOIN security_master AS sm
      ON ld.gvkey = sm.gvkey
     AND ld.iid = sm.iid
    LEFT JOIN annual_flags AS af
      ON ld.gvkey = af.gvkey
    LEFT JOIN quarterly_flags AS qf
      ON ld.gvkey = qf.gvkey
    LEFT JOIN recent_volume AS rv
      ON ld.gvkey = rv.gvkey
     AND ld.iid = rv.iid
    WHERE (%(universe_filter)s = false OR sm.is_excluded_universe = false)
    ORDER BY
        flag_a DESC,
        flag_b DESC,
        flag_d DESC,
        ld.volume_ratio DESC NULLS LAST
    LIMIT 10
    """
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
                "security_feature_snapshot",
                "annual_growth_history",
                "quarterly_growth_history",
            ]
            require_tables(cur, tables)
            for table in tables:
                count = scalar(cur, f"SELECT COUNT(*) FROM {table}")
                print(f"{table}: {count:,} rows")

            latest_snapshot_date = scalar(cur, "SELECT MAX(snapshot_date) FROM security_feature_snapshot")
            print(f"Latest snapshot date: {latest_snapshot_date}")
            if latest_snapshot_date is None:
                raise RuntimeError("security_feature_snapshot has no rows.")

            cur.execute("""
                SELECT
                    COUNT(*) AS latest_rows,
                    COUNT(sm.gvkey) AS joined_master_rows
                FROM security_feature_snapshot AS s
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
                    FROM security_feature_snapshot
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
                "Strict n=10%, annual=3, quarterly=4, q=5, m=3",
                {
                    "selected_date": latest_snapshot_date,
                    "n_pct": 0.10,
                    "annual_years": 3,
                    "quarter_count": 4,
                    "q": 5,
                    "m": 3,
                    "universe_filter": True,
                },
            )
            run_sample_query(
                cur,
                "Relaxed n=5%, annual=2, quarterly=2, q=3, m=2",
                {
                    "selected_date": latest_snapshot_date,
                    "n_pct": 0.05,
                    "annual_years": 2,
                    "quarter_count": 2,
                    "q": 3,
                    "m": 2,
                    "universe_filter": True,
                },
            )


if __name__ == "__main__":
    main()

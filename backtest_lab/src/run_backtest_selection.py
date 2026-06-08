from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.db import connect_supabase, require_tables, table_count  # noqa: E402
from backtest_lab.src.parameter_grid import grid_parameter_names  # noqa: E402


SELECTION_SQL = """
WITH params AS (
    SELECT *
    FROM backtest_parameter_set
    WHERE parameter_set_name = %(parameter_set_name)s
),
daily_flags AS (
    SELECT
        p.parameter_set_id,
        d.snapshot_date,
        d.gvkey,
        d.iid,
        m.ticker,
        m.company_name,
        d.close_price,
        d.adjusted_close_price,
        (
            annual_check.valid_count = p.annual_years
            AND annual_check.pass_count = p.annual_years
        ) AS flag_a,
        (
            quarterly_check.valid_count = p.quarter_count
            AND quarterly_check.pass_count = p.quarter_count
        ) AS flag_b,
        d.volume_ratio >= p.volume_ratio_threshold AS flag_c,
        recent_volume.surge_days >= p.volume_surge_min_days AS flag_d,
        (
            d.ma20 IS NOT NULL
            AND d.ma50 IS NOT NULL
            AND d.ma100 IS NOT NULL
            AND d.ma50 <> 0
            AND d.ma100 <> 0
            AND d.ma20 / d.ma50 BETWEEN 1 - p.daily_ma_tolerance_pct / 100.0
                                  AND 1 + p.daily_ma_tolerance_pct / 100.0
            AND d.ma20 / d.ma100 BETWEEN 1 - p.daily_ma_tolerance_pct / 100.0
                                   AND 1 + p.daily_ma_tolerance_pct / 100.0
            AND d.ma50 / d.ma100 BETWEEN 1 - p.daily_ma_tolerance_pct / 100.0
                                   AND 1 + p.daily_ma_tolerance_pct / 100.0
        ) AS flag_e,
        (
            d.future_daily_ma20 IS NOT NULL
            AND d.future_daily_ma50 IS NOT NULL
            AND d.future_daily_ma100 IS NOT NULL
            AND d.future_daily_ma50 <> 0
            AND d.future_daily_ma100 <> 0
            AND d.future_daily_ma20 / d.future_daily_ma50 BETWEEN 1 - p.daily_ma_tolerance_pct / 100.0
                                                           AND 1 + p.daily_ma_tolerance_pct / 100.0
            AND d.future_daily_ma20 / d.future_daily_ma100 BETWEEN 1 - p.daily_ma_tolerance_pct / 100.0
                                                            AND 1 + p.daily_ma_tolerance_pct / 100.0
            AND d.future_daily_ma50 / d.future_daily_ma100 BETWEEN 1 - p.daily_ma_tolerance_pct / 100.0
                                                            AND 1 + p.daily_ma_tolerance_pct / 100.0
        ) AS flag_f
    FROM params p
    JOIN backtest_daily_feature_snapshot d
      ON d.snapshot_date >= p.start_date
     AND (p.end_date IS NULL OR d.snapshot_date <= p.end_date)
    LEFT JOIN backtest_security_master m
      ON m.gvkey = d.gvkey
     AND m.iid = d.iid
    JOIN LATERAL (
        SELECT
            COUNT(*)::integer AS valid_count,
            COUNT(*) FILTER (
                WHERE annual_revenue_growth >= p.annual_growth_pct
                  AND annual_operating_income_growth >= p.annual_growth_pct
            )::integer AS pass_count
        FROM (
            SELECT annual_revenue_growth, annual_operating_income_growth
            FROM (
                SELECT
                    annual_revenue_growth,
                    annual_operating_income_growth,
                    ROW_NUMBER() OVER (ORDER BY a.datadate DESC) AS rn
                FROM annual_growth_history a
                WHERE a.gvkey = d.gvkey
                  AND a.datadate <= d.snapshot_date
                  AND a.annual_revenue_growth IS NOT NULL
                  AND a.annual_operating_income_growth IS NOT NULL
            ) ranked_annual
            WHERE rn <= p.annual_years
        ) recent_annual
    ) annual_check ON true
    JOIN LATERAL (
        SELECT
            COUNT(*)::integer AS valid_count,
            COUNT(*) FILTER (
                WHERE quarterly_revenue_growth >= p.quarterly_growth_pct
                  AND quarterly_operating_income_growth >= p.quarterly_growth_pct
            )::integer AS pass_count
        FROM (
            SELECT quarterly_revenue_growth, quarterly_operating_income_growth
            FROM (
                SELECT
                    quarterly_revenue_growth,
                    quarterly_operating_income_growth,
                    ROW_NUMBER() OVER (ORDER BY q.datadate DESC) AS rn
                FROM quarterly_growth_history q
                WHERE q.gvkey = d.gvkey
                  AND q.datadate <= d.snapshot_date
                  AND q.quarterly_revenue_growth IS NOT NULL
                  AND q.quarterly_operating_income_growth IS NOT NULL
            ) ranked_quarterly
            WHERE rn <= p.quarter_count
        ) recent_quarterly
    ) quarterly_check ON true
    JOIN LATERAL (
        SELECT COUNT(*) FILTER (
            WHERE hist.volume_ratio >= p.volume_ratio_threshold
        )::integer AS surge_days
        FROM backtest_daily_feature_snapshot hist
        WHERE hist.gvkey = d.gvkey
          AND hist.iid = d.iid
          AND hist.snapshot_date BETWEEN d.snapshot_date - INTERVAL '3 months'
                                    AND d.snapshot_date
    ) recent_volume ON true
),
af_candidates AS (
    SELECT
        parameter_set_id,
        'A_F'::text AS screen_type,
        snapshot_date AS selected_date,
        gvkey,
        iid,
        ticker,
        company_name,
        close_price AS selected_price,
        adjusted_close_price AS selected_adjusted_price,
        flag_a,
        flag_b,
        flag_c,
        flag_d,
        flag_e,
        flag_f,
        NULL::boolean AS flag_g,
        NULL::boolean AS flag_h,
        ROW_NUMBER() OVER (
            PARTITION BY parameter_set_id, gvkey, iid
            ORDER BY snapshot_date
        ) AS rn
    FROM daily_flags
    WHERE flag_a AND flag_b AND flag_c AND flag_d AND flag_e AND flag_f
),
weekly_flags AS (
    SELECT
        f.*,
        (
            w.weekly_ma5 IS NOT NULL
            AND w.weekly_ma10 IS NOT NULL
            AND w.weekly_ma30 IS NOT NULL
            AND w.weekly_ma10 <> 0
            AND w.weekly_ma30 <> 0
            AND w.weekly_ma5 / w.weekly_ma10 BETWEEN 1 - p.weekly_ma_tolerance_pct / 100.0
                                                AND 1 + p.weekly_ma_tolerance_pct / 100.0
            AND w.weekly_ma5 / w.weekly_ma30 BETWEEN 1 - p.weekly_ma_tolerance_pct / 100.0
                                                AND 1 + p.weekly_ma_tolerance_pct / 100.0
            AND w.weekly_ma10 / w.weekly_ma30 BETWEEN 1 - p.weekly_ma_tolerance_pct / 100.0
                                                 AND 1 + p.weekly_ma_tolerance_pct / 100.0
        ) AS flag_g,
        (
            w.future_weekly_ma5 IS NOT NULL
            AND w.future_weekly_ma10 IS NOT NULL
            AND w.future_weekly_ma30 IS NOT NULL
            AND w.future_weekly_ma10 <> 0
            AND w.future_weekly_ma30 <> 0
            AND w.future_weekly_ma5 / w.future_weekly_ma10 BETWEEN 1 - p.weekly_ma_tolerance_pct / 100.0
                                                               AND 1 + p.weekly_ma_tolerance_pct / 100.0
            AND w.future_weekly_ma5 / w.future_weekly_ma30 BETWEEN 1 - p.weekly_ma_tolerance_pct / 100.0
                                                               AND 1 + p.weekly_ma_tolerance_pct / 100.0
            AND w.future_weekly_ma10 / w.future_weekly_ma30 BETWEEN 1 - p.weekly_ma_tolerance_pct / 100.0
                                                                AND 1 + p.weekly_ma_tolerance_pct / 100.0
        ) AS flag_h
    FROM daily_flags f
    JOIN params p
      ON p.parameter_set_id = f.parameter_set_id
    JOIN backtest_weekly_feature_snapshot w
      ON w.week_end_date = f.snapshot_date
     AND w.gvkey = f.gvkey
     AND w.iid = f.iid
),
ah_candidates AS (
    SELECT
        parameter_set_id,
        'A_H'::text AS screen_type,
        snapshot_date AS selected_date,
        gvkey,
        iid,
        ticker,
        company_name,
        close_price AS selected_price,
        adjusted_close_price AS selected_adjusted_price,
        flag_a,
        flag_b,
        flag_c,
        flag_d,
        flag_e,
        flag_f,
        flag_g,
        flag_h,
        ROW_NUMBER() OVER (
            PARTITION BY parameter_set_id, gvkey, iid
            ORDER BY snapshot_date
        ) AS rn
    FROM weekly_flags
    WHERE flag_a AND flag_b AND flag_c AND flag_d AND flag_e AND flag_f AND flag_g AND flag_h
),
selected AS (
    SELECT * FROM af_candidates WHERE rn = 1
    UNION ALL
    SELECT * FROM ah_candidates WHERE rn = 1
)
INSERT INTO backtest_selection_event (
    parameter_set_id,
    screen_type,
    selected_date,
    gvkey,
    iid,
    ticker,
    company_name,
    selected_price,
    selected_adjusted_price,
    flag_a,
    flag_b,
    flag_c,
    flag_d,
    flag_e,
    flag_f,
    flag_g,
    flag_h
)
SELECT
    parameter_set_id,
    screen_type,
    selected_date,
    gvkey,
    iid,
    ticker,
    company_name,
    selected_price,
    selected_adjusted_price,
    flag_a,
    flag_b,
    flag_c,
    flag_d,
    flag_e,
    flag_f,
    flag_g,
    flag_h
FROM selected
ON CONFLICT (parameter_set_id, screen_type, gvkey, iid)
DO UPDATE SET
    selected_date = EXCLUDED.selected_date,
    ticker = EXCLUDED.ticker,
    company_name = EXCLUDED.company_name,
    selected_price = EXCLUDED.selected_price,
    selected_adjusted_price = EXCLUDED.selected_adjusted_price,
    flag_a = EXCLUDED.flag_a,
    flag_b = EXCLUDED.flag_b,
    flag_c = EXCLUDED.flag_c,
    flag_d = EXCLUDED.flag_d,
    flag_e = EXCLUDED.flag_e,
    flag_f = EXCLUDED.flag_f,
    flag_g = EXCLUDED.flag_g,
    flag_h = EXCLUDED.flag_h;
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run temporary backtest stock selection.")
    parser.add_argument(
        "--parameter-set-name",
        help="Run one grid parameter set. If omitted, all 16 grid combinations run.",
    )
    args = parser.parse_args()
    parameter_set_names = (
        [args.parameter_set_name]
        if args.parameter_set_name
        else grid_parameter_names()
    )

    with connect_supabase() as conn:
        require_tables(
            conn,
            [
                "backtest_parameter_set",
                "backtest_daily_feature_snapshot",
                "backtest_weekly_feature_snapshot",
                "backtest_selection_event",
                "annual_growth_history",
                "quarterly_growth_history",
            ],
        )
        before = table_count(conn, "backtest_selection_event")
        with conn.transaction():
            with conn.cursor() as cur:
                total_affected = 0
                for parameter_set_name in parameter_set_names:
                    print(f"Running selection for {parameter_set_name}...")
                    cur.execute(SELECTION_SQL, {"parameter_set_name": parameter_set_name})
                    total_affected += max(cur.rowcount, 0)
        after = table_count(conn, "backtest_selection_event")

    print(f"Backtest parameter sets processed: {len(parameter_set_names):,}")
    print(f"Rows affected: {total_affected:,}")
    print(f"Selection rows before: {before:,}")
    print(f"Selection rows after: {after:,}")


if __name__ == "__main__":
    main()

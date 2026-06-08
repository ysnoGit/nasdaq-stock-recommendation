SELECT
    'backtest_security_master' AS table_name,
    COUNT(*) AS rows
FROM backtest_security_master
UNION ALL
SELECT 'backtest_daily_feature_snapshot', COUNT(*) FROM backtest_daily_feature_snapshot
UNION ALL
SELECT 'backtest_weekly_feature_snapshot', COUNT(*) FROM backtest_weekly_feature_snapshot
UNION ALL
SELECT 'backtest_parameter_set', COUNT(*) FROM backtest_parameter_set
UNION ALL
SELECT 'backtest_selection_event', COUNT(*) FROM backtest_selection_event
UNION ALL
SELECT 'backtest_price_flow_3m', COUNT(*) FROM backtest_price_flow_3m;

SELECT
    MIN(snapshot_date) AS min_daily_snapshot_date,
    MAX(snapshot_date) AS max_daily_snapshot_date,
    COUNT(*) AS daily_rows,
    COUNT(DISTINCT (gvkey, iid)) AS daily_securities,
    COUNT(*) FILTER (WHERE daily_f_confirmed_using_date IS NOT NULL) AS daily_rows_with_future_f_inputs
FROM backtest_daily_feature_snapshot;

SELECT
    MIN(week_end_date) AS min_week_end_date,
    MAX(week_end_date) AS max_week_end_date,
    COUNT(*) AS weekly_rows,
    COUNT(DISTINCT (gvkey, iid)) AS weekly_securities,
    COUNT(*) FILTER (WHERE weekly_h_confirmed_using_date IS NOT NULL) AS weekly_rows_with_future_h_inputs
FROM backtest_weekly_feature_snapshot;

SELECT
    snapshot_date,
    COUNT(*) AS duplicate_daily_keys
FROM (
    SELECT snapshot_date, gvkey, iid, COUNT(*) AS key_count
    FROM backtest_daily_feature_snapshot
    GROUP BY snapshot_date, gvkey, iid
    HAVING COUNT(*) > 1
) duplicates
GROUP BY snapshot_date
ORDER BY snapshot_date
LIMIT 20;

SELECT
    week_end_date,
    COUNT(*) AS duplicate_weekly_keys
FROM (
    SELECT week_end_date, gvkey, iid, COUNT(*) AS key_count
    FROM backtest_weekly_feature_snapshot
    GROUP BY week_end_date, gvkey, iid
    HAVING COUNT(*) > 1
) duplicates
GROUP BY week_end_date
ORDER BY week_end_date
LIMIT 20;

SELECT
    week_start_date,
    COUNT(DISTINCT week_end_date) AS week_end_partitions
FROM backtest_weekly_feature_snapshot
GROUP BY week_start_date
HAVING COUNT(DISTINCT week_end_date) > 1
ORDER BY week_start_date
LIMIT 20;

SELECT
    parameter_set_id,
    parameter_set_name,
    annual_growth_pct,
    quarterly_growth_pct,
    annual_years,
    quarter_count,
    volume_ratio_threshold,
    volume_surge_min_days,
    daily_ma_tolerance_pct,
    weekly_ma_tolerance_pct
FROM backtest_parameter_set
WHERE parameter_set_name LIKE 'grid\_%' ESCAPE '\'
ORDER BY parameter_set_name;

SELECT
    parameter_set_id,
    screen_type,
    COUNT(*) AS selection_rows,
    MIN(selected_date) AS earliest_selected_date,
    MAX(selected_date) AS latest_selected_date,
    COUNT(*) FILTER (WHERE NOT (flag_a AND flag_b AND flag_c AND flag_d AND flag_e AND flag_f)) AS bad_a_f_flags,
    COUNT(*) FILTER (
        WHERE screen_type = 'A_H'
          AND NOT (flag_g AND flag_h)
    ) AS bad_a_h_flags
FROM backtest_selection_event
GROUP BY parameter_set_id, screen_type
ORDER BY parameter_set_id, screen_type;

SELECT
    e.parameter_set_id,
    e.screen_type,
    COUNT(DISTINCT e.selection_event_id) AS selected_events,
    COUNT(f.price_flow_id) AS price_flow_rows,
    MIN(f.period_start_date) AS first_flow_start,
    MAX(f.period_end_date) AS last_flow_end
FROM backtest_selection_event e
LEFT JOIN backtest_price_flow_3m f
  ON f.selection_event_id = e.selection_event_id
GROUP BY e.parameter_set_id, e.screen_type
ORDER BY e.parameter_set_id, e.screen_type;

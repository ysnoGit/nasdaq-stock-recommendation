SELECT COUNT(*) AS parameter_count FROM backtest_parameter_set;

SELECT
    annual_growth_pct, quarterly_growth_pct, annual_years, quarter_count,
    volume_ratio_threshold, volume_surge_min_days, daily_ma_tolerance_pct,
    weekly_ma_tolerance_pct, COUNT(*)
FROM backtest_parameter_set
GROUP BY
    annual_growth_pct, quarterly_growth_pct, annual_years, quarter_count,
    volume_ratio_threshold, volume_surge_min_days, daily_ma_tolerance_pct,
    weekly_ma_tolerance_pct
HAVING COUNT(*) > 1;

SELECT parameter_set_id, screen_type, gvkey, iid, COUNT(*)
FROM backtest_selection_outcome
GROUP BY parameter_set_id, screen_type, gvkey, iid
HAVING COUNT(*) > 1;

SELECT
    screen_type,
    COUNT(*) AS outcome_rows,
    COUNT(DISTINCT parameter_set_id) AS parameter_sets_with_results,
    COUNT(DISTINCT gvkey || '-' || iid) AS unique_securities,
    MIN(signal_date) AS earliest_signal_date,
    MAX(signal_date) AS latest_signal_date,
    MIN(selected_date) AS earliest_actionable_selected_date,
    MAX(selected_date) AS latest_actionable_selected_date
FROM backtest_selection_outcome
GROUP BY screen_type;

SELECT
    p.parameter_set_id, p.annual_growth_pct, p.quarterly_growth_pct,
    p.annual_years, p.quarter_count, p.volume_ratio_threshold,
    p.volume_surge_min_days, p.daily_ma_tolerance_pct,
    p.weekly_ma_tolerance_pct, o.screen_type,
    COUNT(o.outcome_id) AS selected_stock_count
FROM backtest_parameter_set p
LEFT JOIN backtest_selection_outcome o ON p.parameter_set_id = o.parameter_set_id
GROUP BY
    p.parameter_set_id, p.annual_growth_pct, p.quarterly_growth_pct,
    p.annual_years, p.quarter_count, p.volume_ratio_threshold,
    p.volume_surge_min_days, p.daily_ma_tolerance_pct,
    p.weekly_ma_tolerance_pct, o.screen_type
ORDER BY p.parameter_set_id, o.screen_type;

SELECT COUNT(*) AS rows_with_missing_core_price_outcome
FROM backtest_selection_outcome
WHERE selected_price IS NULL OR latest_price IS NULL OR high_price IS NULL
   OR low_price IS NULL OR high_price_date IS NULL OR low_price_date IS NULL;

SELECT COUNT(*) AS bad_date_rows
FROM backtest_selection_outcome
WHERE latest_price_date < selected_date
   OR high_price_date < selected_date
   OR low_price_date < selected_date;

SELECT COUNT(*) AS bad_confirmation_timing_rows
FROM backtest_selection_outcome
WHERE signal_date IS NULL
   OR f_confirmation_date IS NULL
   OR f_confirmation_date <= signal_date
   OR selected_date < f_confirmation_date
   OR (
       screen_type = 'A_F'
       AND (
           selected_date <> f_confirmation_date
           OR g_confirmation_date IS NOT NULL
           OR h_confirmation_date IS NOT NULL
       )
   )
   OR (
       screen_type = 'A_H'
       AND (
           g_confirmation_date IS NULL
           OR h_confirmation_date IS NULL
           OR g_confirmation_date < signal_date
           OR h_confirmation_date <= g_confirmation_date
           OR selected_date <> h_confirmation_date
       )
   );

SELECT COUNT(*) AS bad_price_rows
FROM backtest_selection_outcome
WHERE high_price < low_price;

SELECT * FROM backtest_run_log ORDER BY run_id DESC LIMIT 10;

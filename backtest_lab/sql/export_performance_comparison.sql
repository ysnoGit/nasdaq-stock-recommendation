SELECT
    p.parameter_set_id,
    p.parameter_set_name,
    p.annual_growth_pct,
    p.quarterly_growth_pct,
    p.annual_years,
    p.quarter_count,
    p.volume_ratio_threshold,
    p.volume_surge_min_days,
    o.screen_type,
    COUNT(*) AS sample_size,
    COUNT(o.return_6m_pct) AS sample_size_6m,
    ROUND(AVG(o.return_6m_pct), 2) AS avg_return_6m_pct,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.return_6m_pct)
            FILTER (WHERE o.return_6m_pct IS NOT NULL)::numeric,
        2
    ) AS median_return_6m_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE o.return_6m_pct > 0)
            / NULLIF(COUNT(o.return_6m_pct), 0),
        2
    ) AS win_rate_6m_pct,
    COUNT(o.return_1y_pct) AS sample_size_1y,
    ROUND(AVG(o.return_1y_pct), 2) AS avg_return_1y_pct,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.return_1y_pct)
            FILTER (WHERE o.return_1y_pct IS NOT NULL)::numeric,
        2
    ) AS median_return_1y_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE o.return_1y_pct > 0)
            / NULLIF(COUNT(o.return_1y_pct), 0),
        2
    ) AS win_rate_1y_pct,
    COUNT(o.return_2y_pct) AS sample_size_2y,
    ROUND(AVG(o.return_2y_pct), 2) AS avg_return_2y_pct,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY o.return_2y_pct)
            FILTER (WHERE o.return_2y_pct IS NOT NULL)::numeric,
        2
    ) AS median_return_2y_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE o.return_2y_pct > 0)
            / NULLIF(COUNT(o.return_2y_pct), 0),
        2
    ) AS win_rate_2y_pct,
    MIN(o.signal_date) AS earliest_signal_date,
    MAX(o.signal_date) AS latest_signal_date,
    MIN(o.selected_date) AS earliest_entry_date,
    MAX(o.selected_date) AS latest_entry_date
FROM backtest_parameter_set p
JOIN backtest_selection_outcome o USING (parameter_set_id)
GROUP BY
    p.parameter_set_id,
    p.parameter_set_name,
    p.annual_growth_pct,
    p.quarterly_growth_pct,
    p.annual_years,
    p.quarter_count,
    p.volume_ratio_threshold,
    p.volume_surge_min_days,
    o.screen_type
ORDER BY o.screen_type, sample_size DESC, p.parameter_set_id;

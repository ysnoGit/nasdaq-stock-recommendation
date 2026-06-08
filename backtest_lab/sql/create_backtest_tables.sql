CREATE TABLE IF NOT EXISTS backtest_security_master (
    gvkey text NOT NULL,
    iid text NOT NULL,
    ticker text,
    company_name text,
    exchange_code text,
    security_status text,
    security_type text,
    is_active boolean,
    is_excluded_universe boolean NOT NULL DEFAULT false,
    exclusion_reason text,
    first_seen_date date,
    last_seen_date date,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gvkey, iid)
);

CREATE INDEX IF NOT EXISTS idx_backtest_security_master_ticker
    ON backtest_security_master (ticker);

CREATE INDEX IF NOT EXISTS idx_backtest_security_master_active
    ON backtest_security_master (is_active);

CREATE TABLE IF NOT EXISTS backtest_daily_feature_snapshot (
    snapshot_date date NOT NULL,
    gvkey text NOT NULL,
    iid text NOT NULL,
    close_price numeric,
    adjusted_close_price numeric,
    volume numeric,
    volume_ma30 numeric,
    volume_ratio numeric,
    volume_lookback_start_date date,
    volume_lookback_end_date date,
    ma20 numeric,
    ma50 numeric,
    ma100 numeric,
    daily_f_confirmed_using_date date,
    future_daily_ma20 numeric,
    future_daily_ma50 numeric,
    future_daily_ma100 numeric,
    future_daily_close_price numeric,
    future_daily_adjusted_close_price numeric,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, gvkey, iid)
);

CREATE INDEX IF NOT EXISTS idx_backtest_daily_snapshot_date
    ON backtest_daily_feature_snapshot (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_backtest_daily_security_date
    ON backtest_daily_feature_snapshot (gvkey, iid, snapshot_date);

CREATE INDEX IF NOT EXISTS idx_backtest_daily_volume_ratio
    ON backtest_daily_feature_snapshot (snapshot_date, volume_ratio DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_daily_f_confirmed_date
    ON backtest_daily_feature_snapshot (daily_f_confirmed_using_date);

CREATE TABLE IF NOT EXISTS backtest_weekly_feature_snapshot (
    week_start_date date NOT NULL,
    week_end_date date NOT NULL,
    gvkey text NOT NULL,
    iid text NOT NULL,
    weekly_open_price numeric,
    weekly_high_price numeric,
    weekly_low_price numeric,
    weekly_close_price numeric,
    weekly_volume numeric,
    weekly_ma5 numeric,
    weekly_ma10 numeric,
    weekly_ma30 numeric,
    weekly_h_confirmed_using_date date,
    future_weekly_ma5 numeric,
    future_weekly_ma10 numeric,
    future_weekly_ma30 numeric,
    future_weekly_close_price numeric,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (week_end_date, gvkey, iid)
);

CREATE INDEX IF NOT EXISTS idx_backtest_weekly_week_end_date
    ON backtest_weekly_feature_snapshot (week_end_date);

CREATE INDEX IF NOT EXISTS idx_backtest_weekly_week_start_date
    ON backtest_weekly_feature_snapshot (week_start_date);

CREATE INDEX IF NOT EXISTS idx_backtest_weekly_security_date
    ON backtest_weekly_feature_snapshot (gvkey, iid, week_end_date);

CREATE INDEX IF NOT EXISTS idx_backtest_weekly_h_confirmed_date
    ON backtest_weekly_feature_snapshot (weekly_h_confirmed_using_date);

CREATE TABLE IF NOT EXISTS backtest_parameter_set (
    parameter_set_id bigserial PRIMARY KEY,
    parameter_set_name text NOT NULL UNIQUE,
    start_date date NOT NULL DEFAULT date '2022-01-01',
    end_date date,
    annual_growth_pct numeric NOT NULL,
    quarterly_growth_pct numeric NOT NULL,
    annual_years integer NOT NULL,
    quarter_count integer NOT NULL,
    volume_ratio_threshold numeric NOT NULL,
    volume_surge_min_days integer NOT NULL,
    daily_ma_tolerance_pct numeric NOT NULL,
    weekly_ma_tolerance_pct numeric NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backtest_selection_event (
    selection_event_id bigserial PRIMARY KEY,
    parameter_set_id bigint NOT NULL REFERENCES backtest_parameter_set(parameter_set_id),
    screen_type text NOT NULL CHECK (screen_type IN ('A_F', 'A_H')),
    selected_date date NOT NULL,
    gvkey text NOT NULL,
    iid text NOT NULL,
    ticker text,
    company_name text,
    selected_price numeric,
    selected_adjusted_price numeric,
    flag_a boolean NOT NULL,
    flag_b boolean NOT NULL,
    flag_c boolean NOT NULL,
    flag_d boolean NOT NULL,
    flag_e boolean NOT NULL,
    flag_f boolean,
    flag_g boolean,
    flag_h boolean,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (parameter_set_id, screen_type, gvkey, iid)
);

CREATE INDEX IF NOT EXISTS idx_backtest_selection_event_date
    ON backtest_selection_event (selected_date);

CREATE INDEX IF NOT EXISTS idx_backtest_selection_event_type
    ON backtest_selection_event (parameter_set_id, screen_type);

CREATE TABLE IF NOT EXISTS backtest_price_flow_3m (
    price_flow_id bigserial PRIMARY KEY,
    selection_event_id bigint NOT NULL REFERENCES backtest_selection_event(selection_event_id),
    period_index integer NOT NULL,
    period_start_date date NOT NULL,
    period_end_date date NOT NULL,
    trading_days integer NOT NULL,
    start_price numeric,
    end_price numeric,
    high_price numeric,
    low_price numeric,
    avg_price numeric,
    return_pct numeric,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (selection_event_id, period_index)
);

WITH parameter_grid AS (
    SELECT *
    FROM (
        VALUES
            ('grid_ag3_qg3_vr5_vd3', 3, 3, 5, 3),
            ('grid_ag3_qg3_vr5_vd5', 3, 3, 5, 5),
            ('grid_ag3_qg3_vr10_vd3', 3, 3, 10, 3),
            ('grid_ag3_qg3_vr10_vd5', 3, 3, 10, 5),
            ('grid_ag3_qg5_vr5_vd3', 3, 5, 5, 3),
            ('grid_ag3_qg5_vr5_vd5', 3, 5, 5, 5),
            ('grid_ag3_qg5_vr10_vd3', 3, 5, 10, 3),
            ('grid_ag3_qg5_vr10_vd5', 3, 5, 10, 5),
            ('grid_ag5_qg3_vr5_vd3', 5, 3, 5, 3),
            ('grid_ag5_qg3_vr5_vd5', 5, 3, 5, 5),
            ('grid_ag5_qg3_vr10_vd3', 5, 3, 10, 3),
            ('grid_ag5_qg3_vr10_vd5', 5, 3, 10, 5),
            ('grid_ag5_qg5_vr5_vd3', 5, 5, 5, 3),
            ('grid_ag5_qg5_vr5_vd5', 5, 5, 5, 5),
            ('grid_ag5_qg5_vr10_vd3', 5, 5, 10, 3),
            ('grid_ag5_qg5_vr10_vd5', 5, 5, 10, 5)
    ) AS grid(
        parameter_set_name,
        annual_growth_pct,
        quarterly_growth_pct,
        volume_ratio_threshold,
        volume_surge_min_days
    )
)
INSERT INTO backtest_parameter_set (
    parameter_set_name,
    start_date,
    annual_growth_pct,
    quarterly_growth_pct,
    annual_years,
    quarter_count,
    volume_ratio_threshold,
    volume_surge_min_days,
    daily_ma_tolerance_pct,
    weekly_ma_tolerance_pct
)
SELECT
    parameter_set_name,
    date '2022-01-01',
    annual_growth_pct,
    quarterly_growth_pct,
    3,
    4,
    volume_ratio_threshold,
    volume_surge_min_days,
    1,
    2
FROM parameter_grid
ON CONFLICT (parameter_set_name)
DO UPDATE SET
    start_date = EXCLUDED.start_date,
    annual_growth_pct = EXCLUDED.annual_growth_pct,
    quarterly_growth_pct = EXCLUDED.quarterly_growth_pct,
    annual_years = EXCLUDED.annual_years,
    quarter_count = EXCLUDED.quarter_count,
    volume_ratio_threshold = EXCLUDED.volume_ratio_threshold,
    volume_surge_min_days = EXCLUDED.volume_surge_min_days,
    daily_ma_tolerance_pct = EXCLUDED.daily_ma_tolerance_pct,
    weekly_ma_tolerance_pct = EXCLUDED.weekly_ma_tolerance_pct;

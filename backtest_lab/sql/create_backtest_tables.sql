CREATE TABLE IF NOT EXISTS backtest_parameter_set (
    parameter_set_id bigserial PRIMARY KEY,
    parameter_set_name text NOT NULL,
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
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (
        annual_growth_pct,
        quarterly_growth_pct,
        annual_years,
        quarter_count,
        volume_ratio_threshold,
        volume_surge_min_days,
        daily_ma_tolerance_pct,
        weekly_ma_tolerance_pct
    )
);

CREATE TABLE IF NOT EXISTS backtest_selection_outcome (
    outcome_id bigserial PRIMARY KEY,
    parameter_set_id bigint NOT NULL REFERENCES backtest_parameter_set(parameter_set_id),
    screen_type text NOT NULL CHECK (screen_type IN ('A_F', 'A_H')),
    signal_date date,
    f_confirmation_date date,
    g_confirmation_date date,
    h_confirmation_date date,
    selected_date date NOT NULL,
    gvkey text NOT NULL,
    iid text NOT NULL,
    ticker text,
    company_name text,
    selected_price numeric,
    selected_adjusted_price numeric,
    latest_price_date date,
    latest_price numeric,
    latest_adjusted_price numeric,
    high_price numeric,
    high_price_date date,
    low_price numeric,
    low_price_date date,
    return_pct numeric,
    max_return_pct numeric,
    max_drawdown_pct numeric,
    return_6m_date date,
    price_6m numeric,
    return_6m_pct numeric,
    return_1y_date date,
    price_1y numeric,
    return_1y_pct numeric,
    return_2y_date date,
    price_2y numeric,
    return_2y_pct numeric,
    trading_days_after_selection integer,
    flag_a boolean NOT NULL,
    flag_b boolean NOT NULL,
    flag_c boolean NOT NULL,
    flag_d boolean NOT NULL,
    flag_e boolean NOT NULL,
    flag_f boolean,
    flag_g boolean,
    flag_h boolean,
    source_result_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (parameter_set_id, screen_type, gvkey, iid)
);

ALTER TABLE backtest_selection_outcome
    ADD COLUMN IF NOT EXISTS signal_date date,
    ADD COLUMN IF NOT EXISTS f_confirmation_date date,
    ADD COLUMN IF NOT EXISTS g_confirmation_date date,
    ADD COLUMN IF NOT EXISTS h_confirmation_date date,
    ADD COLUMN IF NOT EXISTS return_6m_date date,
    ADD COLUMN IF NOT EXISTS price_6m numeric,
    ADD COLUMN IF NOT EXISTS return_6m_pct numeric,
    ADD COLUMN IF NOT EXISTS return_1y_date date,
    ADD COLUMN IF NOT EXISTS price_1y numeric,
    ADD COLUMN IF NOT EXISTS return_1y_pct numeric,
    ADD COLUMN IF NOT EXISTS return_2y_date date,
    ADD COLUMN IF NOT EXISTS price_2y numeric,
    ADD COLUMN IF NOT EXISTS return_2y_pct numeric;

CREATE INDEX IF NOT EXISTS idx_backtest_outcome_parameter
    ON backtest_selection_outcome (parameter_set_id, screen_type);

CREATE INDEX IF NOT EXISTS idx_backtest_outcome_security
    ON backtest_selection_outcome (gvkey, iid, selected_date);

CREATE TABLE IF NOT EXISTS backtest_run_log (
    run_id bigserial PRIMARY KEY,
    run_name text,
    start_date date,
    end_date date,
    parameter_set_count integer,
    status text,
    local_output_path text,
    s3_output_path text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error_message text
);

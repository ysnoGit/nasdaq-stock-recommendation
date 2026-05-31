CREATE TABLE IF NOT EXISTS security_feature_snapshot (
    snapshot_date date NOT NULL,
    gvkey text NOT NULL,
    iid text NOT NULL,
    ticker text,
    company_name text,
    close_price double precision,
    adjusted_close_price double precision,
    volume double precision,
    volume_ma30 double precision,
    volume_ratio double precision,
    volume_lookback_start_date date,
    volume_lookback_end_date date,
    ma20 double precision,
    ma50 double precision,
    ma100 double precision,
    week_start_date date,
    week_end_date date,
    weekly_close_price double precision,
    wma5 double precision,
    wma10 double precision,
    wma30 double precision,
    daily_f_confirmation_pass boolean,
    daily_f_confirmed_using_date date,
    weekly_h_confirmation_pass boolean,
    weekly_h_confirmed_using_date date,
    is_excluded_universe boolean NOT NULL DEFAULT false,
    exclusion_reason text,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, gvkey, iid)
);

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_ticker
    ON security_feature_snapshot (ticker);

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_snapshot_date
    ON security_feature_snapshot (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_volume_ratio
    ON security_feature_snapshot (snapshot_date, volume_ratio DESC);

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_week
    ON security_feature_snapshot (week_start_date, week_end_date);

CREATE TABLE IF NOT EXISTS annual_growth_history (
    gvkey text NOT NULL,
    fyear integer NOT NULL,
    datadate date,
    annual_rank_desc integer,
    annual_revenue double precision,
    annual_operating_income double precision,
    annual_revenue_growth double precision,
    annual_operating_income_growth double precision,
    source_extract_date date,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gvkey, fyear)
);

CREATE INDEX IF NOT EXISTS idx_annual_growth_history_rank
    ON annual_growth_history (gvkey, annual_rank_desc);

CREATE INDEX IF NOT EXISTS idx_annual_growth_history_fyear
    ON annual_growth_history (fyear);

CREATE TABLE IF NOT EXISTS quarterly_growth_history (
    gvkey text NOT NULL,
    fyearq integer NOT NULL,
    fqtr integer NOT NULL,
    datadate date,
    quarterly_rank_desc integer,
    quarterly_revenue double precision,
    quarterly_operating_income double precision,
    quarterly_revenue_growth double precision,
    quarterly_operating_income_growth double precision,
    source_extract_date date,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (gvkey, fyearq, fqtr)
);

CREATE INDEX IF NOT EXISTS idx_quarterly_growth_history_rank
    ON quarterly_growth_history (gvkey, quarterly_rank_desc);

CREATE INDEX IF NOT EXISTS idx_quarterly_growth_history_period
    ON quarterly_growth_history (fyearq, fqtr);

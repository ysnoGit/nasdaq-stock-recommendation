CREATE TABLE IF NOT EXISTS security_master (
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

CREATE INDEX IF NOT EXISTS idx_security_master_ticker
    ON security_master (ticker);

CREATE INDEX IF NOT EXISTS idx_security_master_company_name
    ON security_master (company_name);

CREATE INDEX IF NOT EXISTS idx_security_master_is_excluded_universe
    ON security_master (is_excluded_universe);

CREATE INDEX IF NOT EXISTS idx_security_master_is_active
    ON security_master (is_active);

CREATE TABLE IF NOT EXISTS security_feature_snapshot (
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
    week_start_date date,
    week_end_date date,
    weekly_close_price numeric,
    wma5 numeric,
    wma10 numeric,
    wma30 numeric,
    daily_f_confirmation_pass boolean,
    daily_f_confirmed_using_date date,
    future_daily_ma20 numeric,
    future_daily_ma50 numeric,
    future_daily_ma100 numeric,
    future_daily_close_price numeric,
    future_daily_adjusted_close_price numeric,
    weekly_h_confirmation_pass boolean,
    weekly_h_confirmed_using_date date,
    future_weekly_wma5 numeric,
    future_weekly_wma10 numeric,
    future_weekly_wma30 numeric,
    future_weekly_close_price numeric,
    source_s3_path text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, gvkey, iid)
);

ALTER TABLE security_feature_snapshot
    ADD COLUMN IF NOT EXISTS future_daily_ma20 numeric,
    ADD COLUMN IF NOT EXISTS future_daily_ma50 numeric,
    ADD COLUMN IF NOT EXISTS future_daily_ma100 numeric,
    ADD COLUMN IF NOT EXISTS future_daily_close_price numeric,
    ADD COLUMN IF NOT EXISTS future_daily_adjusted_close_price numeric,
    ADD COLUMN IF NOT EXISTS future_weekly_wma5 numeric,
    ADD COLUMN IF NOT EXISTS future_weekly_wma10 numeric,
    ADD COLUMN IF NOT EXISTS future_weekly_wma30 numeric,
    ADD COLUMN IF NOT EXISTS future_weekly_close_price numeric;

COMMENT ON COLUMN security_feature_snapshot.daily_f_confirmation_pass IS
    'Deprecated. F is computed dynamically from future_daily_* columns and user-selected daily MA tolerance.';

COMMENT ON COLUMN security_feature_snapshot.weekly_h_confirmation_pass IS
    'Deprecated. H is computed dynamically from future_weekly_* columns and user-selected weekly MA tolerance.';

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_snapshot_date
    ON security_feature_snapshot (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_volume_ratio
    ON security_feature_snapshot (snapshot_date, volume_ratio DESC);

CREATE INDEX IF NOT EXISTS idx_security_feature_snapshot_week
    ON security_feature_snapshot (week_start_date, week_end_date);

CREATE TABLE IF NOT EXISTS security_daily_feature_snapshot (
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

CREATE INDEX IF NOT EXISTS idx_security_daily_snapshot_date
    ON security_daily_feature_snapshot (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_security_daily_security_date
    ON security_daily_feature_snapshot (gvkey, iid, snapshot_date);

CREATE INDEX IF NOT EXISTS idx_security_daily_volume_ratio
    ON security_daily_feature_snapshot (snapshot_date, volume_ratio DESC);

CREATE INDEX IF NOT EXISTS idx_security_daily_f_confirmed_date
    ON security_daily_feature_snapshot (daily_f_confirmed_using_date);

CREATE TABLE IF NOT EXISTS security_weekly_feature_snapshot (
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

CREATE INDEX IF NOT EXISTS idx_security_weekly_week_end_date
    ON security_weekly_feature_snapshot (week_end_date);

CREATE INDEX IF NOT EXISTS idx_security_weekly_week_start_date
    ON security_weekly_feature_snapshot (week_start_date);

CREATE INDEX IF NOT EXISTS idx_security_weekly_security_date
    ON security_weekly_feature_snapshot (gvkey, iid, week_end_date);

CREATE INDEX IF NOT EXISTS idx_security_weekly_h_confirmed_date
    ON security_weekly_feature_snapshot (weekly_h_confirmed_using_date);

CREATE OR REPLACE VIEW security_weekly_feature_snapshot_compat AS
SELECT
    week_start_date,
    week_end_date,
    gvkey,
    iid,
    weekly_open_price,
    weekly_high_price,
    weekly_low_price,
    weekly_close_price,
    weekly_volume,
    weekly_ma5 AS wma5,
    weekly_ma10 AS wma10,
    weekly_ma30 AS wma30,
    weekly_h_confirmed_using_date,
    future_weekly_ma5 AS future_weekly_wma5,
    future_weekly_ma10 AS future_weekly_wma10,
    future_weekly_ma30 AS future_weekly_wma30,
    future_weekly_close_price,
    source_s3_path,
    created_at,
    updated_at
FROM security_weekly_feature_snapshot;

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

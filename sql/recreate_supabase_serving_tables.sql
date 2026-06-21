-- Recreate only the production serving layer. Backtest tables are untouched.
DROP VIEW IF EXISTS security_weekly_feature_snapshot_compat;

DROP TABLE IF EXISTS security_daily_feature_snapshot;
DROP TABLE IF EXISTS security_weekly_feature_snapshot;
DROP TABLE IF EXISTS security_feature_snapshot;
DROP TABLE IF EXISTS annual_growth_history;
DROP TABLE IF EXISTS quarterly_growth_history;
DROP TABLE IF EXISTS company_master;
DROP TABLE IF EXISTS security_master;

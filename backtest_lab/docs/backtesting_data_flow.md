# Backtesting Data Flow

```text
Production S3 raw daily Parquet
        |
        v
DuckDB feature build on EC2
        |
        +--> backtest_lab/tmp/daily_features.parquet
        +--> backtest_lab/tmp/weekly_features.parquet
        |
Production S3 growth-history Parquet
        |
        v
Per-parameter DuckDB screening (192 sequential combinations)
        |
        +--> backtest_lab/tmp/results/selections_<parameter_set_id>.parquet
        +--> backtest_lab/tmp/results/outcomes_<parameter_set_id>.parquet
        |
        v
Compact Supabase tables only
        +--> backtest_parameter_set
        +--> backtest_selection_outcome
        +--> backtest_run_log
```

The local `tmp/` directory is deleted at the beginning of the next run. Production S3 prefixes and production Supabase serving tables are never deleted by this lab.

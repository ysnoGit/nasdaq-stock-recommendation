# NASDAQ Stock Recommendation Pipeline

This project builds an AWS EC2 and S3 backed NASDAQ stock screening pipeline using WRDS Compustat data, DuckDB, pandas, and boto3.

## Pipeline Data Flow

The current pipeline follows a `raw -> processed -> results` data layout in S3:

- `raw/`: WRDS Compustat annual, quarterly, and daily security extracts.
- `processed/`: reusable feature tables for fundamental growth, daily market metrics, weekly market metrics, and recent daily volume metrics.
- `results/`: final parameterized screening outputs in Parquet and CSV.

Main EC2/S3 runner:

```bash
python3 server_pipeline/run_full_pipeline.py
```

Main pipeline scripts:

- `server_pipeline/fundamentals/extract_compustat_fundamentals_s3.py`
- `server_pipeline/daily/extract_compustat_daily_incremental_s3.py`
- `server_pipeline/fundamentals/build_fundamental_growth_history_s3.py`
- `server_pipeline/daily/build_daily_market_metrics_s3.py`
- `server_pipeline/daily/build_weekly_market_metrics_s3.py`
- `server_pipeline/daily/build_recent_daily_volume_metrics_s3.py`
- `server_pipeline/screening/build_final_screening_results_s3.py`

Detailed data lineage, output paths, table grains, validation checks, and design notes are documented in:

```text
docs/full_pipeline_data_flow.md
```

For EC2 setup and run commands, see:

```text
docs/ec2_full_pipeline_runbook.md
```

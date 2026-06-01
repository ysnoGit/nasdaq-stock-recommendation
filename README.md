# NASDAQ Stock Recommendation Pipeline

This project builds an AWS EC2 and S3 backed NASDAQ stock feature pipeline using WRDS Compustat data, DuckDB, pandas, boto3, S3, and an optional Supabase serving layer.

## Pipeline Data Flow

The current pipeline follows a `raw -> processed` data layout in S3, with optional serving tables in Supabase:

- `raw/`: WRDS Compustat annual, quarterly, and daily security extracts.
- `processed/`: reusable feature tables for fundamental growth, daily market metrics, weekly market metrics, and recent daily volume metrics.
- Supabase serving layer: application-facing feature tables loaded from processed S3 outputs.

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

Detailed data lineage, output paths, table grains, validation checks, and design notes are documented in:

```text
docs/full_pipeline_data_flow.md
```

Supabase PostgreSQL can be used as an application serving layer on top of the processed S3 Parquet outputs. The loader upserts security feature snapshots plus annual and quarterly growth history without storing credentials in the repository:

```text
docs/supabase_serving_layer.md
```

For EC2 setup and run commands, see:

```text
docs/ec2_full_pipeline_runbook.md
```

## Daily EC2 Batch Automation

The daily production flow can be automated with EventBridge Scheduler, systemd, the full S3 pipeline, the Supabase loader, and optional EC2 self-shutdown. Setup details are in:

```text
docs/daily_ec2_batch_automation.md
```

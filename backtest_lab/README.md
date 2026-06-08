# Backtest Lab

Temporary backtesting workspace for the NASDAQ stock recommendation pipeline.

Everything in this folder is intentionally isolated from the production pipeline and serving layer. The backtest lab reuses existing production S3 raw daily files and existing Supabase growth-history tables; it does not run a new WRDS extraction pipeline.

## Tables

- `backtest_security_master`
- `backtest_daily_feature_snapshot`
- `backtest_weekly_feature_snapshot`
- `backtest_parameter_set`
- `backtest_selection_event`
- `backtest_price_flow_3m`
- 16 materialized result tables named like `backtest_result_ag3_qg3_vr5_vd3`

## Parameter Grid

`backtest_lab/sql/create_backtest_tables.sql` creates 16 grid parameter sets:

- start date: `2022-01-01`
- annual growth threshold choices: `3`, `5`
- quarterly growth threshold choices: `3`, `5`
- annual years: `3`
- quarter count: `4`
- volume ratio threshold choices: `5`, `10`
- volume surge minimum day choices: `3`, `5`
- daily MA tolerance: `1`
- weekly MA tolerance: `2`

The full grid is `2 x 2 x 2 x 2 = 16` combinations. Each combination gets one physical result table after `run_backtest_selection.sh`.

## EC2 Run Sequence

From the repo root on EC2:

```bash
cd /home/ec2-user/projects/nasdaq-stock-recommendation
source venv/bin/activate

export AWS_REGION="ap-northeast-2"
export AWS_DEFAULT_REGION="ap-northeast-2"

Recommended storage-light run:

```bash
bash backtest_lab/scripts/run_backtest_pipeline.sh --start-date 2022-01-01
```

This computes historical daily/weekly features locally with S3/DuckDB and loads only final selections, price-flow summaries, and 16 result tables into Supabase.

The older table-loader scripts are still present for debugging, but do not use them for the full 2022+ backtest unless the Supabase database has enough storage for millions of feature rows:

```bash
export BACKTEST_ALLOW_SUPABASE_FEATURE_LOAD=true
bash backtest_lab/scripts/prepare_backtest_data.sh --start-date 2022-01-01
bash backtest_lab/scripts/run_backtest_selection.sh
```

`SUPABASE_DB_URL` must be set in the environment before running these scripts. Do not paste or commit the value.

The full 2022+ daily feature table is large. If Supabase reports `No space left on device`, the database storage quota is exhausted before selection starts; reduce the backtest date window or increase Supabase database storage before rerunning.

## What Gets Rebuilt

The recommended `run_backtest_pipeline.sh` rebuilds these locally and does not store them in Supabase:

- daily features from existing raw S3 daily Parquet files
- security master from the daily feature identity columns
- weekly features from the rebuilt daily features

Only final backtest outputs are stored in Supabase. The `backtest_daily_feature_snapshot` and `backtest_weekly_feature_snapshot` tables may remain empty in this workflow. Production tables are not deleted.

## Selection Behavior

`run_backtest_selection.sh` runs all 16 parameter combinations by default. It runs both:

- `A_F`: A, B, C, D, E, F
- `A_H`: A, B, C, D, E, F, G, H on completed weekly dates where `daily.snapshot_date = weekly.week_end_date`

For each `parameter_set_id + screen_type + gvkey + iid`, only the earliest selected date is stored.

After the canonical `backtest_selection_event` and `backtest_price_flow_3m` tables are updated, the script rebuilds one table per parameter combination, for example:

- `backtest_result_ag3_qg3_vr5_vd3`
- `backtest_result_ag3_qg3_vr5_vd5`
- `backtest_result_ag5_qg5_vr10_vd5`

Future daily and weekly confirmation columns are inputs for F and H. If future values are null, the condition is treated as pending and does not pass.

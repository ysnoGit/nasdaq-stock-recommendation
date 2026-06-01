# Full Pipeline Data Flow

## Project Overview

This repository implements an EC2 and S3 backed NASDAQ stock feature pipeline. It extracts raw Compustat data from WRDS, writes raw Parquet files to S3, and builds processed feature tables with DuckDB. An optional Supabase PostgreSQL serving layer can load selected processed features for indexed application queries without replacing S3 as the data lake.

The current production-style entry point is:

```bash
python3 server_pipeline/run_full_pipeline.py
```

For EC2, use:

```bash
bash scripts/run_full_pipeline_ec2.sh
```

The runner supports:

```bash
python3 server_pipeline/run_full_pipeline.py --skip-wrds
python3 server_pipeline/run_full_pipeline.py --only extraction
python3 server_pipeline/run_full_pipeline.py --only transform
```

`--skip-wrds` is useful after raw WRDS data already exists in S3.

## Architecture Summary

The pipeline follows a simple lake-style layout:

| Layer | Purpose | S3 prefix |
|---|---|---|
| Raw | WRDS extracts with minimal feature processing | `raw/` |
| Processed | Reusable feature tables for fundamentals, daily market metrics, weekly market metrics, and recent volume | `processed/` |
| Serving | Optional relational tables for dashboards and apps | Supabase PostgreSQL |

Central configuration lives in [`server_pipeline/config.py`](../server_pipeline/config.py). The default bucket is `nasdaq-stock-recommendation`; the default AWS region is `ap-northeast-2`, with overrides through `AWS_REGION` or `AWS_DEFAULT_REGION`.

WRDS authentication is handled by [`server_pipeline/utils/wrds_connection.py`](../server_pipeline/utils/wrds_connection.py). It requires `WRDS_USERNAME` in the environment and reads the password through `~/.pgpass`; no WRDS password is stored in code.

DuckDB S3 access is configured in [`server_pipeline/s3_duckdb.py`](../server_pipeline/s3_duckdb.py). It installs/loads DuckDB `httpfs`, uses boto3 credentials, and sets DuckDB `s3_region` to the same configured AWS region.

## Full Pipeline Order

This is the actual order defined in [`server_pipeline/run_full_pipeline.py`](../server_pipeline/run_full_pipeline.py).

| Step | Script | Category | Input source | Output path | Format | Grain | Partitioned | Validation checks |
|---:|---|---|---|---|---|---|---|---|
| 1 | `server_pipeline/fundamentals/extract_compustat_fundamentals_s3.py` | Extraction | WRDS `comp.funda`, `comp.fundq`, filtered by active NASDAQ securities from `comp.secd` | `raw/compustat_annual/latest/compustat_annual.parquet`; `raw/compustat_quarterly/latest/compustat_quarterly.parquet` | Parquet | Annual: `gvkey, fyear`; quarterly: `gvkey, fyearq, fqtr` | Stable `latest` snapshot only | Row counts, unique GVKEYs, fiscal/date ranges, missing key measures, duplicate annual/quarterly keys, old `extract_date=...` cleanup logging |
| 2 | `server_pipeline/daily/extract_compustat_daily_incremental_s3.py` | Extraction | WRDS `comp.secd` latest trading dates | `raw/compustat_daily_security/year=YYYY/month=MM/date=YYYY-MM-DD/compustat_daily_security_YYYY-MM-DD.parquet` | Parquet | `gvkey, iid, date` | Yes, by year/month/date | Latest dates printed, rows per date, unique tickers, empty-date warning |
| 3 | `server_pipeline/fundamentals/build_fundamental_growth_history_s3.py` | Transformation | Raw annual and quarterly `latest` fundamentals | `processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet`; `processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet` | Parquet | Annual: `gvkey, fyear`; quarterly: `gvkey, fyearq, fqtr` | No, single feature history files | Row counts, unique GVKEYs, ranges, valid growth-pair counts, duplicate key counts |
| 4 | `server_pipeline/daily/build_daily_market_metrics_s3.py` | Feature engineering | Raw daily security files, including yearly warm-up files and date-partitioned daily raw files | `processed/daily_market_metrics/year=YYYY/month=MM/date=YYYY-MM-DD/daily_market_metrics_YYYY-MM-DD.parquet` | Parquet | `gvkey, iid, date` | Yes, by year/month/date | Selected raw files, target dates, row counts, unique tickers, date range, duplicate `gvkey/iid/date`, flag counts |
| 5 | `server_pipeline/daily/build_weekly_market_metrics_s3.py` | Feature engineering | Raw daily security files | `processed/weekly_market_metrics/year=YYYY/week_start_date=YYYY-MM-DD/weekly_market_metrics_YYYY-MM-DD.parquet` | Parquet | `gvkey, iid, week_start_date` | Yes, by year/week_start_date | Duplicate ticker-week, duplicate security-week, one week end per week start, ticker coverage warning, legacy `week_end_date` cleanup logging |
| 6 | `server_pipeline/daily/build_recent_daily_volume_metrics_s3.py` | Feature engineering | Date-partitioned daily market metrics | `processed/recent_daily_volume_metrics/recent_daily_volume_metrics.parquet` | Parquet | `gvkey, iid, date` inside recent window | No, intentionally one snapshot file | Daily partition count, output rows, unique tickers, date range, latest date |

## Data Lineage Diagram

```mermaid
flowchart TD
    WRDSF["WRDS Compustat fundamentals<br/>comp.funda, comp.fundq"] --> EF["extract_compustat_fundamentals_s3.py"]
    WRDSD["WRDS Compustat daily security<br/>comp.secd"] --> ED["extract_compustat_daily_incremental_s3.py"]

    EF --> RAWF["S3 raw fundamentals<br/>raw/compustat_annual/...<br/>raw/compustat_quarterly/..."]
    ED --> RAWD["S3 raw daily security<br/>raw/compustat_daily_security/year=/month=/date=/"]

    RAWF --> FGH["build_fundamental_growth_history_s3.py"]
    FGH --> PFH["S3 processed fundamental history<br/>processed/annual_fundamental_growth_history/...<br/>processed/quarterly_fundamental_growth_history/..."]

    RAWD --> DMM["build_daily_market_metrics_s3.py"]
    RAWD --> WMM["build_weekly_market_metrics_s3.py"]

    DMM --> PDM["S3 processed daily market metrics<br/>processed/daily_market_metrics/year=/month=/date=/"]
    WMM --> PWM["S3 processed weekly market metrics<br/>processed/weekly_market_metrics/year=/week_start_date=/"]

    PDM --> RDV["build_recent_daily_volume_metrics_s3.py"]
    RDV --> PRV["S3 recent volume snapshot<br/>processed/recent_daily_volume_metrics/recent_daily_volume_metrics.parquet"]

    PDM --> SUPA["Supabase serving tables<br/>security_feature_snapshot<br/>annual_growth_history<br/>quarterly_growth_history"]
    PWM --> SUPA
    PFH --> SUPA
```

## Data Layer Explanation

### `raw/`

The raw layer stores WRDS extracts with lightweight normalization only. Daily raw files include adjusted close price computed from raw close and adjustment factor, but the main purpose is to preserve source-like data in S3.

### `processed/`

The processed layer stores reusable feature tables:

- Fundamental growth history from annual and quarterly fundamentals.
- Daily market indicators and daily helper flags.
- Weekly market indicators and weekly helper flags.
- Recent daily volume snapshot used as a compact feature layer.

### Supabase Serving Layer

Supabase is optional and is used only as a serving layer for app-facing relational queries. S3 remains the durable raw and processed data lake. The serving loader reads processed Parquet files and upserts:

```text
security_feature_snapshot
annual_growth_history
quarterly_growth_history
```

Setup and commands are documented in [`docs/supabase_serving_layer.md`](supabase_serving_layer.md).

## Step-By-Step Processing

### A. WRDS Raw Data Extraction

`server_pipeline/fundamentals/extract_compustat_fundamentals_s3.py` extracts annual fundamentals from WRDS `comp.funda` and quarterly fundamentals from WRDS `comp.fundq`. Both queries restrict records to industrial, consolidated, standard-format data and to GVKEYs seen in active NASDAQ securities from `comp.secd` where `exchg = 14`, `secstat = 'A'`, and `tpci = '0'`.

Important annual fields include `gvkey`, `datadate`, `fyear`, `ticker`, `company_name`, `sale`, `revt`, `oiadp`, `at`, `csho`, `prcc_f`, and `mkvalt`.

Important quarterly fields include `gvkey`, `datadate`, `fyearq`, `fqtr`, `ticker`, `company_name`, `saleq`, `revtq`, `oiadpq`, `atq`, `cshoq`, `prccq`, and `mkvaltq`.

The script writes only stable `latest` files. `latest` means the current canonical raw fundamentals snapshot used by downstream processing:

```text
raw/compustat_annual/latest/compustat_annual.parquet
raw/compustat_quarterly/latest/compustat_quarterly.parquet
```

Old `raw/compustat_annual/extract_date=...` and `raw/compustat_quarterly/extract_date=...` prefixes are deleted by default after the latest files are written. The script logs each exact S3 object before deleting it. To clean old versioned extracts without downloading from WRDS, run:

```bash
python3 server_pipeline/fundamentals/extract_compustat_fundamentals_s3.py --cleanup-old-extracts-only
```

`server_pipeline/daily/extract_compustat_daily_incremental_s3.py` extracts latest daily security rows from WRDS `comp.secd`. It first asks WRDS for the most recent trading dates, then downloads each date and writes date-partitioned raw Parquet:

```text
raw/compustat_daily_security/year=YYYY/month=MM/date=YYYY-MM-DD/compustat_daily_security_YYYY-MM-DD.parquet
```

### B. Fundamental Growth History

`server_pipeline/fundamentals/build_fundamental_growth_history_s3.py` reads the annual and quarterly `latest` raw files from S3.

Annual growth is calculated at `gvkey, fyear` grain. The script uses `COALESCE(sale, revt)` as annual revenue and `oiadp` as annual operating income. It deduplicates annual rows with `ROW_NUMBER() OVER (PARTITION BY gvkey, fyear ORDER BY datadate DESC)` and keeps `rn = 1`. It then calculates year-over-year revenue and operating income growth with `LAG(...)` over each GVKEY ordered by fiscal year.

Quarterly growth is calculated at `gvkey, fyearq, fqtr` grain. The script uses `COALESCE(saleq, revtq)` as quarterly revenue and `oiadpq` as quarterly operating income. It deduplicates by `gvkey, fyearq, fqtr`, then joins each quarter to the same quarter in the prior fiscal year.

The outputs are single history files:

```text
processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet
processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet
```

Both outputs include rank fields (`annual_rank_desc`, `quarterly_rank_desc`) so downstream serving or screening logic can select recent annual or quarterly windows.

### C. Daily Market Metrics

`server_pipeline/daily/build_daily_market_metrics_s3.py` reads raw daily security files from S3. It selects a target set of recent trading dates and a warm-up window long enough to calculate moving averages. It includes yearly raw files for historical warm-up where needed and date-partitioned raw files for 2026 and later.

Daily metrics are calculated at `gvkey, iid, date` grain. The script deduplicates source rows by `gvkey, iid, date`, calculates:

- `ma20`, `ma50`, `ma100`
- `volume_ma30`, excluding the current day
- `volume_ratio`
- daily moving-average ratio fields
- `daily_ma_cluster_ratio`
- helper `flag_e`
- helper `flag_f`

The output is partitioned by trading date:

```text
processed/daily_market_metrics/year=YYYY/month=MM/date=YYYY-MM-DD/daily_market_metrics_YYYY-MM-DD.parquet
```

### D. Weekly Market Metrics

`server_pipeline/daily/build_weekly_market_metrics_s3.py` builds weekly indicators from raw daily security data. Weekly metrics exist because some screening conditions are based on weekly moving averages and weekly moving-average crossover behavior, which is distinct from daily price/volume behavior.

The output grain is one row per `gvkey, iid, week_start_date`.

The fixed weekly partitioning logic uses `week_start_date` as the stable S3 partition key:

```text
processed/weekly_market_metrics/year=YYYY/week_start_date=YYYY-MM-DD/weekly_market_metrics_YYYY-MM-DD.parquet
```

The file still keeps:

- `week_end_date`: market-wide latest available trading date in that calendar week.
- `security_week_last_trade_date`: latest available trading date for that security in that week.
- `data_as_of_date`: latest raw daily date used by the build.

This design prevents the same calendar week from producing multiple physical folders as new trading days arrive. For example, a week can update from Wednesday to Thursday internally through `week_end_date` and `data_as_of_date`, while the physical partition remains the same `week_start_date=...` folder.

The script avoids duplicate weekly rows by ranking daily rows within `gvkey, iid, DATE_TRUNC('week', date)` and keeping the latest row in each week. It validates duplicate ticker-week and duplicate security-week keys, checks that each `week_start_date` has only one `week_end_date`, and warns if completed weekly partitions have unusually low ticker coverage.

The script can also clean old legacy `week_end_date=...` prefixes:

```bash
python3 server_pipeline/daily/build_weekly_market_metrics_s3.py --cleanup-legacy-week-end
```

### E. Recent Daily Volume Metrics

`server_pipeline/daily/build_recent_daily_volume_metrics_s3.py` scans the date-partitioned daily market metrics and creates a recent-volume feature snapshot over the latest configurable lookback window. The default is three months.

This step intentionally writes one single feature snapshot file:

```text
processed/recent_daily_volume_metrics/recent_daily_volume_metrics.parquet
```

It is different from `daily_market_metrics` and `weekly_market_metrics`. Those are time-series feature tables partitioned by date/week. `recent_daily_volume_metrics` is a compact feature layer for recent volume analysis and screening support; it stores recent rows with `latest_date` and `window_start_date` columns so consumers can see the snapshot window.

### F. Dynamic Signal Evaluation

The full pipeline now stops after processed feature creation. It does not create final `results/screening_results/...` files by default. Dynamic A-H conditions should be evaluated in the application or serving layer from processed S3 features and Supabase serving tables.

Major signal fields:

| Flag | Meaning in code |
|---|---|
| `flag_a` | Annual revenue and operating income growth meet the configured `n_pct` threshold for the configured annual lookback count. |
| `flag_b` | Quarterly revenue and operating income growth meet the configured `n_pct` threshold for the configured quarterly lookback count. |
| `flag_ab` | Both `flag_a` and `flag_b` are true. |
| `flag_c` | Latest daily `volume_ratio` is at least `q`. |
| `flag_d` | Count of recent surge days with `volume_ratio >= q` is at least `m`. |
| `flag_cd` | Both `flag_c` and `flag_d` are true. |
| `flag_e` | Daily moving averages are clustered within the helper threshold from the daily metrics step. |
| `flag_f` | Daily moving-average crossover helper flag from the daily metrics step. |
| `flag_g` | Weekly moving averages are clustered within the helper threshold from the weekly metrics step. |
| `flag_h` | Weekly moving-average crossover helper flag from the weekly metrics step. |
| `flag_all` | `flag_a`, `flag_b`, `flag_c`, `flag_d`, `flag_f`, and `flag_h` are all true. |

Because Condition D depends on configurable `q` and `m` values, it should be calculated dynamically from daily `volume_ratio` history instead of stored as one fixed count.

## Data Grain Table

| Dataset | Grain |
|---|---|
| Raw annual fundamentals | `gvkey, fyear` after downstream deduplication |
| Raw quarterly fundamentals | `gvkey, fyearq, fqtr` after downstream deduplication |
| Raw daily security | `gvkey, iid, date` |
| Annual growth history | `gvkey, fyear` |
| Quarterly growth history | `gvkey, fyearq, fqtr` |
| Daily market metrics | `gvkey, iid, date` |
| Weekly market metrics | `gvkey, iid, week_start_date` |
| Recent daily volume metrics | `gvkey, iid, date` within latest snapshot window |

## S3 Output Table

| Output | Path pattern | Partitioning |
|---|---|---|
| Annual fundamentals latest | `raw/compustat_annual/latest/compustat_annual.parquet` | Stable latest file |
| Quarterly fundamentals latest | `raw/compustat_quarterly/latest/compustat_quarterly.parquet` | Stable latest file |
| Daily security raw | `raw/compustat_daily_security/year=YYYY/month=MM/date=YYYY-MM-DD/compustat_daily_security_YYYY-MM-DD.parquet` | Year/month/date |
| Annual growth history | `processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet` | Single file |
| Quarterly growth history | `processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet` | Single file |
| Daily market metrics | `processed/daily_market_metrics/year=YYYY/month=MM/date=YYYY-MM-DD/daily_market_metrics_YYYY-MM-DD.parquet` | Year/month/date |
| Weekly market metrics | `processed/weekly_market_metrics/year=YYYY/week_start_date=YYYY-MM-DD/weekly_market_metrics_YYYY-MM-DD.parquet` | Year/week_start_date |
| Recent daily volume metrics | `processed/recent_daily_volume_metrics/recent_daily_volume_metrics.parquet` | Single snapshot file |

## Validation Checks Table

| Step | Validation output |
|---|---|
| Fundamentals extraction | Row counts, unique GVKEYs, fiscal/date ranges, missing revenue/income fields, duplicate key counts |
| Daily extraction | Latest trading dates, row count, unique ticker count, empty-date warning |
| Fundamental growth history | Row counts, unique GVKEYs, ranges, valid growth-pair counts, duplicate annual/quarterly keys |
| Daily market metrics | Selected files, target dates, output rows, unique tickers, date range, duplicate `gvkey/iid/date`, helper flag counts |
| Weekly market metrics | Selected files, row counts, unique tickers, week ranges, duplicate ticker-week, duplicate `gvkey/iid/week_start_date`, one week end per week start, ticker coverage warning, old prefix cleanup logging |
| Recent daily volume metrics | Number of input daily partitions, output rows, unique tickers, date range, latest date |

## Known Design Choices

- `weekly_market_metrics` is partitioned by `week_start_date` because it is a time-series feature table and the partition must remain stable while the current week updates.
- `recent_daily_volume_metrics` is intentionally kept as a single feature snapshot file because it represents the current recent-volume feature layer for downstream inspection and screening support.
- The full runner stops after processed feature creation; application-facing queries should use Supabase serving tables loaded from those processed features.
- `server_pipeline/` is the current EC2/S3-backed implementation. Some files under `scripts/` are older local utilities or one-off checks and are not part of the current full runner.

## Current Limitations

- The extraction steps require WRDS network access, `WRDS_USERNAME`, and a correctly permissioned `~/.pgpass`.
- Daily and weekly market metrics are incremental by default. Larger historical rebuilds require explicit arguments, such as `--start-week-date` for weekly metrics.
- `recent_daily_volume_metrics` is produced as a snapshot file, not a partitioned historical feature table.
- Universe-audit fields are not yet promoted into the processed serving inputs; the Supabase loader currently sets `is_excluded_universe = false` and `exclusion_reason = null`.

## Next Improvement Ideas

- Add a lightweight data quality report that summarizes S3 row counts and date coverage after each full run.
- Add CI checks for import/compile validation and simple static checks.
- Add optional historical rebuild commands for daily and weekly processed features.
- Consider an app or notebook view that computes dynamic A-H conditions from Supabase without exposing secrets.

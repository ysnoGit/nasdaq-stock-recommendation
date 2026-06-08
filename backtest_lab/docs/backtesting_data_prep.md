# Backtesting Data Prep

## Purpose

This folder creates a temporary backtesting dataset without changing production serving tables.

The backtest starts at `2022-01-01` by default and reads existing S3 daily raw Parquet files under:

```text
s3://nasdaq-stock-recommendation/raw/compustat_daily_security/
```

It does not extract from WRDS.

The recommended workflow computes historical features locally with S3/DuckDB and stores only final selections, price-flow summaries, and materialized result tables in Supabase. This avoids loading millions of historical daily/weekly feature rows into Supabase.

## Feature Build

Daily features are rebuilt locally from raw daily data with a warm-up window so moving averages are available at the start of the backtest window.

Daily fields include:

- close and adjusted close
- volume
- 30-day prior volume average
- volume ratio
- MA20, MA50, MA100
- next daily MA/price values for condition F

Weekly features are built locally from completed official U.S. trading weeks only.

Weekly fields include:

- weekly open, high, low, close, volume
- prior completed weekly MA5, MA10, MA30
- next weekly MA/price values for condition H

## Selection Logic

The parameter set controls the thresholds:

- A: latest `annual_years` rows in `annual_growth_history` as of selected date
- B: latest `quarter_count` rows in `quarterly_growth_history` as of selected date
- C: current daily `volume_ratio`
- D: count of volume-ratio surges over the previous 3 months
- E: current daily MA20/50/100 clustering
- F: next daily MA20/50/100 clustering
- G: current weekly MA5/10/30 clustering
- H: next weekly MA5/10/30 clustering

For the current experiment, the selectable grid is intentionally limited to 16 combinations:

- `annual_growth_pct`: `3`, `5`
- `quarterly_growth_pct`: `3`, `5`
- `volume_ratio_threshold`: `5`, `10`
- `volume_surge_min_days`: `3`, `5`

The fixed values are:

- `annual_years`: `3`
- `quarter_count`: `4`
- `daily_ma_tolerance_pct`: `1`
- `weekly_ma_tolerance_pct`: `2`

Annual and quarterly growth-history values are decimal ratios. The backtest converts the user-facing percentage choices before comparison, so `3` means `0.03` and `5` means `0.05`.

`A_F` is evaluated on daily dates from 2022 onward.

`A_H` is evaluated only on completed weekly dates where the daily snapshot date equals the weekly end date and the same `gvkey/iid` exists in both tables.

`backtest_selection_event` remains the canonical Supabase table with `parameter_set_id`. After selection and price-flow generation, 16 physical result tables are materialized from it. Their names encode the parameter combination, for example `backtest_result_ag3_qg5_vr10_vd3`.

## Validation

Run:

```bash
bash backtest_lab/scripts/validate_backtest_data.sh
```

The validation SQL reports:

- row counts for all backtest tables
- daily and weekly Supabase feature row counts, which can be zero in the storage-light workflow
- duplicate daily and weekly keys
- multiple weekly partitions for one calendar week
- selected event counts by parameter set and screen type
- price-flow coverage by screen type
- existence and row counts for the 16 materialized result tables

Empty result sets in duplicate checks are good.

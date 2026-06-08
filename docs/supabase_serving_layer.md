# Supabase Serving Layer

## Purpose

S3 remains the source of truth for raw and processed pipeline data. Supabase PostgreSQL is the application serving layer for indexed relational queries, dashboards, and portfolio demos.

The serving layer now uses five normalized active tables:

| Table | Grain | Purpose |
|---|---|---|
| `security_master` | `gvkey, iid` | Security identity, active status, and universe filter fields. |
| `security_daily_feature_snapshot` | `snapshot_date, gvkey, iid` | Daily price, volume, daily MA, and future daily inputs for F. |
| `security_weekly_feature_snapshot` | `week_end_date, gvkey, iid` | Completed weekly bars, weekly MA, and future weekly inputs for H. |
| `annual_growth_history` | `gvkey, fyear` | Annual fundamental growth history. |
| `quarterly_growth_history` | `gvkey, fyearq, fqtr` | Quarterly fundamental growth history. |

`security_master` owns display and mostly-static identity fields such as `ticker`, `company_name`, `exchange_code`, `security_status`, `security_type`, `is_active`, `is_excluded_universe`, and `exclusion_reason`.

`security_daily_feature_snapshot` and `security_weekly_feature_snapshot` no longer own display identity fields. Query them through `security_master` for ticker, company name, active status, and universe filtering.

The old mixed `security_feature_snapshot` table is left in place as a deprecated compatibility table. New serving queries should not use it.

## Inputs

The loader reads these processed S3 outputs:

```text
s3://nasdaq-stock-recommendation/processed/daily_market_metrics/year=*/month=*/date=*/daily_market_metrics_YYYY-MM-DD.parquet
s3://nasdaq-stock-recommendation/processed/weekly_market_metrics/year=*/week_start_date=*/weekly_market_metrics_YYYY-MM-DD.parquet
s3://nasdaq-stock-recommendation/processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet
s3://nasdaq-stock-recommendation/processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet
```

The loader does not read `processed/recent_daily_volume_metrics/`. That snapshot belongs to the older S3-only screening design and is no longer part of the active serving flow.

## Loader

Schema:

```text
sql/create_supabase_serving_tables.sql
```

Loader:

```text
server_pipeline/serving/load_processed_features_to_supabase.py
```

Run all tables:

```bash
bash scripts/load_processed_features_to_supabase.sh --apply-schema
```

Normal recurring load after schema exists:

```bash
bash scripts/load_processed_features_to_supabase.sh
```

One-table options:

```bash
bash scripts/load_processed_features_to_supabase.sh --only security
bash scripts/load_processed_features_to_supabase.sh --only security-master
bash scripts/load_processed_features_to_supabase.sh --only daily
bash scripts/load_processed_features_to_supabase.sh --only weekly
bash scripts/load_processed_features_to_supabase.sh --only annual
bash scripts/load_processed_features_to_supabase.sh --only quarterly
```

`--only security` loads `security_master`, `security_daily_feature_snapshot`, and `security_weekly_feature_snapshot`.

## Dynamic Screening

Queries should join daily/weekly feature tables to `security_master` for ticker, company name, active status, and universe filtering:

```sql
SELECT
    d.snapshot_date,
    sm.ticker,
    sm.company_name,
    d.gvkey,
    d.iid,
    d.volume_ratio,
    sm.is_excluded_universe,
    sm.exclusion_reason
FROM security_daily_feature_snapshot AS d
JOIN security_master AS sm
  ON d.gvkey = sm.gvkey
 AND d.iid = sm.iid
WHERE d.snapshot_date = :selected_date
  AND (:universe_filter = false OR sm.is_excluded_universe = false);
```

Conditions A-H should be evaluated dynamically:

| Condition | Serving-layer source |
|---|---|
| A | `annual_growth_history`, using configurable annual growth thresholds and lookback counts. |
| B | `quarterly_growth_history`, using configurable quarterly growth thresholds and lookback counts. |
| C | `security_daily_feature_snapshot.volume_ratio`, using the selected snapshot date and configurable `volume_ratio_threshold`. |
| D | Three months of `security_daily_feature_snapshot.volume_ratio` history with configurable `volume_ratio_threshold` and `volume_surge_min_days`. |
| E | `security_daily_feature_snapshot.ma20`, `ma50`, `ma100`, using configurable `daily_ma_tolerance_pct`. |
| F | `future_daily_ma20`, `future_daily_ma50`, `future_daily_ma100`, using configurable `daily_ma_tolerance_pct`. |
| G | `security_weekly_feature_snapshot.weekly_ma5`, `weekly_ma10`, `weekly_ma30`, using configurable `weekly_ma_tolerance_pct`. |
| H | `future_weekly_ma5`, `future_weekly_ma10`, `future_weekly_ma30`, using configurable `weekly_ma_tolerance_pct`. |

For weekly rows, `week_end_date` means the official final U.S. exchange trading session of that calendar week. It is usually Friday, but it can be Thursday or another earlier session when Friday is a market holiday. The pipeline uses the `exchange_calendars` U.S. equities calendar, preferring XNAS/NASDAQ when available, instead of hardcoded weekday logic.

Stored F/H future-input fields preserve future-data semantics:

- `daily_f_confirmed_using_date` must be greater than `snapshot_date`.
- `future_daily_ma20`, `future_daily_ma50`, and `future_daily_ma100` come from the next trading row for the same `gvkey, iid`.
- `weekly_h_confirmed_using_date` must be greater than `week_end_date`.
- `future_weekly_ma5`, `future_weekly_ma10`, and `future_weekly_ma30` come from the next completed weekly row for the same `gvkey, iid`.
- `NULL` means the future confirmation row does not exist yet, not that the condition failed.

Deprecated `daily_f_confirmation_pass` and `weekly_h_confirmation_pass` columns in the old mixed table should not be used as final screening truth because F/H depend on user-selected tolerance values. Screening queries should compute F/H dynamically from the future input columns.

Condition D:

```sql
WITH recent_volume AS (
    SELECT
        gvkey,
        iid,
        COUNT(*) FILTER (WHERE volume_ratio >= :q) AS recent_c_count
    FROM security_daily_feature_snapshot
    WHERE snapshot_date BETWEEN (:selected_date::date - INTERVAL '3 months')
                            AND :selected_date::date
    GROUP BY gvkey, iid
)
SELECT recent_c_count >= :m AS flag_d
FROM recent_volume;
```

Because Condition D looks back three months, the serving load must retain at least the latest three months of `security_daily_feature_snapshot` rows.

## Validation

The loader prints:

- S3 bucket and lookback window.
- Selected daily partition count and latest date.
- Input row counts and input columns.
- Built row counts.
- Unique primary-key counts prepared.
- Table row counts before and after load.
- Active `security_master` count compared with the latest snapshot count.

Run table checks:

```sql
select count(*) from security_master;
select count(*) from security_daily_feature_snapshot;
select count(*) from security_weekly_feature_snapshot;
select count(*) from annual_growth_history;
select count(*) from quarterly_growth_history;

select min(snapshot_date), max(snapshot_date), count(distinct snapshot_date)
from security_daily_feature_snapshot;

select min(week_end_date), max(week_end_date), count(distinct week_end_date)
from security_weekly_feature_snapshot;

select count(*)
from security_daily_feature_snapshot
where volume_ratio is not null;

select s.snapshot_date, s.gvkey, s.iid, count(*)
from security_daily_feature_snapshot as s
group by s.snapshot_date, s.gvkey, s.iid
having count(*) > 1;

select s.week_end_date, s.gvkey, s.iid, count(*)
from security_weekly_feature_snapshot as s
group by s.week_end_date, s.gvkey, s.iid
having count(*) > 1;
```

Latest snapshot join check:

```sql
with latest as (
    select max(snapshot_date) as snapshot_date
    from security_daily_feature_snapshot
)
select
    count(*) as latest_rows,
    count(sm.gvkey) as joined_master_rows
from security_daily_feature_snapshot as s
cross join latest as l
left join security_master as sm
  on s.gvkey = sm.gvkey
 and s.iid = sm.iid
where s.snapshot_date = l.snapshot_date;
```

Future F/H input checks:

```sql
select count(*) as bad_daily_future_date_rows
from security_daily_feature_snapshot
where daily_f_confirmed_using_date is not null
  and daily_f_confirmed_using_date <= snapshot_date;

select count(*) as bad_weekly_future_date_rows
from security_weekly_feature_snapshot
where weekly_h_confirmed_using_date is not null
  and weekly_h_confirmed_using_date <= week_end_date;

select count(*) as bad_daily_null_rows
from security_daily_feature_snapshot
where daily_f_confirmed_using_date is null
  and (
      future_daily_ma20 is not null
      or future_daily_ma50 is not null
      or future_daily_ma100 is not null
  );

select count(*) as bad_weekly_null_rows
from security_weekly_feature_snapshot
where weekly_h_confirmed_using_date is null
  and (
      future_weekly_ma5 is not null
      or future_weekly_ma10 is not null
      or future_weekly_ma30 is not null
  );
```

Daily future-input availability:

```sql
select
    snapshot_date,
    count(*) as rows,
    count(*) filter (
        where daily_f_confirmed_using_date is not null
    ) as rows_with_future_daily_confirmation,
    count(*) filter (
        where daily_f_confirmed_using_date is null
    ) as rows_pending_daily_confirmation
from security_daily_feature_snapshot
group by snapshot_date
order by snapshot_date desc
limit 20;
```

Weekly future-input availability:

```sql
select
    week_end_date,
    count(*) as rows,
    count(*) filter (
        where weekly_h_confirmed_using_date is not null
    ) as rows_with_future_weekly_confirmation,
    count(*) filter (
        where weekly_h_confirmed_using_date is null
    ) as rows_pending_weekly_confirmation
from security_weekly_feature_snapshot
group by week_end_date
order by week_end_date desc
limit 20;
```

## Sample Screening Test

Run:

```bash
python3 scripts/run_supabase_sample_screening_test.py
```

The script reads `SUPABASE_DB_URL` from the environment, validates all four tables, checks latest snapshot joins to `security_master`, verifies dynamic Condition D can be calculated, and prints strict and relaxed sample rows with `ticker` and `company_name` from `security_master`.

## Existing Supabase Projects

If your Supabase project already has the older `security_feature_snapshot` shape with `ticker`, `company_name`, `is_excluded_universe`, and `exclusion_reason`, read:

```text
docs/supabase_migration_notes.md
```

The migration path is non-destructive: create/backfill `security_master`, update queries to join it, and only remove old snapshot identity columns after the app is tested.

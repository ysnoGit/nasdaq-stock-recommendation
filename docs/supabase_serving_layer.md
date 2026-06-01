# Supabase Serving Layer

## Purpose

S3 remains the source of truth for raw and processed pipeline data. Supabase PostgreSQL is a serving layer for application queries, dashboards, and portfolio demos that need indexed relational tables instead of scanning Parquet from S3.

The serving loader reads processed S3 Parquet outputs and upserts them into three tables:

| Table | Purpose | Primary key |
|---|---|---|
| `security_feature_snapshot` | Latest rolling daily security features with daily and weekly technical signals. | `snapshot_date, gvkey, iid` |
| `annual_growth_history` | Annual fundamental growth history by security and fiscal year. | `gvkey, fyear` |
| `quarterly_growth_history` | Quarterly fundamental growth history by security and fiscal quarter. | `gvkey, fyearq, fqtr` |

The SQL schema lives in:

```text
sql/create_supabase_serving_tables.sql
```

The loader lives in:

```text
server_pipeline/serving/load_processed_features_to_supabase.py
```

## Inputs

The loader reads these processed S3 outputs:

```text
s3://nasdaq-stock-recommendation/processed/daily_market_metrics/year=*/month=*/date=*/daily_market_metrics_YYYY-MM-DD.parquet
s3://nasdaq-stock-recommendation/processed/weekly_market_metrics/year=*/week_start_date=*/weekly_market_metrics_YYYY-MM-DD.parquet
s3://nasdaq-stock-recommendation/processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet
s3://nasdaq-stock-recommendation/processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet
```

The loader does not read `processed/recent_daily_volume_metrics/`. That snapshot belongs to the older S3-only screening design and is no longer part of the active serving flow.

`security_feature_snapshot` loads the latest rolling window from daily market metrics. The default is three months:

```bash
python3 server_pipeline/serving/load_processed_features_to_supabase.py --only security --lookback-months 3
```

Weekly metrics are joined by `gvkey, iid, week_start_date`. The weekly S3 partition must use the stable `week_start_date` layout. Legacy `week_end_date=...` folders are not loaded by this serving script.

## Environment

Do not store Supabase credentials in code, docs, or Git. Set the connection URL only in the shell or EC2 environment:

```bash
export SUPABASE_DB_URL="postgresql://..."
```

Use the project default AWS region:

```bash
export AWS_REGION="ap-northeast-2"
export AWS_DEFAULT_REGION="ap-northeast-2"
```

## EC2 Commands

From the EC2 project checkout:

```bash
cd ~/projects/nasdaq-stock-recommendation
source venv/bin/activate
python3 -m pip install -r requirements.txt

export AWS_REGION="ap-northeast-2"
export AWS_DEFAULT_REGION="ap-northeast-2"
export SUPABASE_DB_URL="postgresql://..."

python3 server_pipeline/serving/load_processed_features_to_supabase.py --apply-schema
```

The wrapper script is equivalent:

```bash
bash scripts/load_processed_features_to_supabase.sh --apply-schema
```

To load one table at a time:

```bash
python3 server_pipeline/serving/load_processed_features_to_supabase.py --only security --lookback-months 3
python3 server_pipeline/serving/load_processed_features_to_supabase.py --only annual
python3 server_pipeline/serving/load_processed_features_to_supabase.py --only quarterly
```

## Validation

The loader prints:

- S3 bucket and lookback window.
- Selected daily partition count and latest date.
- Input row counts and input columns.
- Built row counts.
- Unique primary key counts prepared.
- Table row counts before and after load.

Run these SQL checks in Supabase after the load:

```sql
select count(*) from security_feature_snapshot;
select min(snapshot_date), max(snapshot_date), count(*) from security_feature_snapshot;
select count(*) from annual_growth_history;
select count(*) from quarterly_growth_history;
select min(snapshot_date), max(snapshot_date), count(distinct snapshot_date)
from security_feature_snapshot;
select count(*) from security_feature_snapshot
where volume_ratio is not null;

select snapshot_date, gvkey, iid, count(*)
from security_feature_snapshot
group by snapshot_date, gvkey, iid
having count(*) > 1;
```

The duplicate-key query should return zero rows.

## Current Signal Notes

The serving table stores daily F confirmation and weekly H confirmation fields from the processed daily and weekly metrics.

Conditions should be evaluated dynamically by the app or screening layer from the loaded history and feature tables:

| Condition | Serving-layer source |
|---|---|
| A | `annual_growth_history`, using configurable annual growth thresholds and lookback counts. |
| B | `quarterly_growth_history`, using configurable quarterly growth thresholds and lookback counts. |
| C | `security_feature_snapshot.volume_ratio`, using the chosen latest `snapshot_date` and configurable `q` threshold. |
| D | `security_feature_snapshot` daily `volume_ratio` history over the selected lookback window, using configurable `q` and `m`. |
| E | `security_feature_snapshot` daily moving average columns: `ma20`, `ma50`, `ma100`. |
| F | `security_feature_snapshot.daily_f_confirmation_pass`, mapped from processed daily `flag_f`. |
| G | `security_feature_snapshot` weekly moving average columns: `wma5`, `wma10`, `wma30`. |
| H | `security_feature_snapshot.weekly_h_confirmation_pass`, mapped from processed weekly `flag_h`. |

Do not store a fixed `recent_volume_signal_count` in Supabase. Condition D should stay dynamic and should be calculated from daily `volume_ratio` history using configurable screening parameters. This keeps the serving layer reusable when `q` or `m` changes.

Example Condition D query:

```sql
WITH recent_volume AS (
    SELECT
        gvkey,
        iid,
        COUNT(*) FILTER (WHERE volume_ratio >= :q) AS recent_c_count
    FROM security_feature_snapshot
    WHERE snapshot_date BETWEEN (:selected_date::date - INTERVAL '3 months')
                            AND :selected_date::date
    GROUP BY gvkey, iid
)
SELECT recent_c_count >= :m AS flag_d
FROM recent_volume;
```

Because this query looks back three months, the serving load must retain at least the latest three months of `security_feature_snapshot` rows.

The current processed daily and weekly feature files do not carry upstream universe-audit fields. For now, the serving loader sets:

```text
is_excluded_universe = false
exclusion_reason = null
```

If universe-audit fields are promoted into a processed feature file later, map those fields in `build_security_feature_rows()`.

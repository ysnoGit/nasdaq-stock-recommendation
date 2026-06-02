# Supabase Migration Notes

These notes are for existing Supabase projects that were created before the normalized `security_master` table was added.

## What Changed

The serving model now uses:

```text
security_master
security_feature_snapshot
annual_growth_history
quarterly_growth_history
```

`security_master` owns security identity, display fields, active status, and universe filter fields. `security_feature_snapshot` focuses on time-varying feature values.

## Safe Migration Path

1. Apply the new non-destructive schema:

```bash
bash scripts/load_processed_features_to_supabase.sh --apply-schema
```

2. Backfill `security_master` and reload snapshots:

```bash
bash scripts/load_processed_features_to_supabase.sh --only security
```

3. Update application queries to join:

```sql
security_feature_snapshot s
join security_master sm
  on s.gvkey = sm.gvkey
 and s.iid = sm.iid
```

4. Select display fields and universe filter fields from `security_master`, not from `security_feature_snapshot`.

5. Run:

```bash
python3 scripts/run_supabase_sample_screening_test.py
```

## Do Not Drop Old Columns Immediately

Older Supabase projects may still have these columns in `security_feature_snapshot`:

```text
ticker
company_name
is_excluded_universe
exclusion_reason
```

The new loader no longer writes those columns, but the migration does not automatically drop them. Leave them in place until the app and sample queries are tested against `security_master`.

Avoid destructive `DROP COLUMN` changes in production unless explicitly planned and backed up.

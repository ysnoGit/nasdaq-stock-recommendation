# Backtest Lab

This directory is an isolated historical screening experiment. It reuses production S3 raw and processed data, but it does not modify the production pipeline or create another WRDS extraction system.

## Storage Strategy

Large daily and weekly feature data stays on EC2 as compressed Parquet under `backtest_lab/tmp/`. Each of the 192 parameter combinations is processed separately with DuckDB. Supabase stores only:

- `backtest_parameter_set`: 192 parameter combinations
- `backtest_selection_outcome`: compact earliest-selection and price-outcome summaries
- `backtest_run_log`: run status and diagnostics

The runner deletes prior generated files under `backtest_lab/tmp/` at the start of every run. It never deletes production S3 data or automatically drops Supabase tables.

`backtest_selection_outcome.selected_date` is the actionable confirmation date,
not the original A-E signal date. A-F entries begin on the next trading row used
to confirm F. A-H entries begin on the following completed weekly row used to
confirm H. Separate `signal_date`, `f_confirmation_date`,
`g_confirmation_date`, and `h_confirmation_date` columns preserve the timing
audit trail.

## Parameter Grid

| Parameter | Choices |
| --- | --- |
| `annual_growth_pct` | 2, 3 |
| `quarterly_growth_pct` | 2, 3 |
| `annual_years` | 2, 3 |
| `quarter_count` | 2, 3, 4 |
| `volume_ratio_threshold` | 2, 3, 4, 5 |
| `volume_surge_min_days` | 2, 3 |
| `daily_ma_tolerance_pct` | 1 |
| `weekly_ma_tolerance_pct` | 2 |

Total: `2 x 2 x 2 x 3 x 4 x 2 = 192`.

Growth percentages are user-facing values. For example, `annual_growth_pct = 2` is compared to the stored decimal growth ratio `0.02`.

## Run

```bash
cd /home/ec2-user/projects/nasdaq-stock-recommendation
source venv/bin/activate

bash backtest_lab/scripts/run_backtest.sh --start-date 2022-01-01
bash backtest_lab/scripts/validate_results.sh
```

Debug one parameter set:

```bash
bash backtest_lab/scripts/run_backtest.sh --start-date 2022-01-01 --parameter-set-id 1
```

Clean generated local outputs manually:

```bash
bash backtest_lab/scripts/cleanup_outputs.sh
```

## Safe Reruns

Parameter insertion is idempotent. Before loading outcomes for one parameter set, the runner deletes only that parameter set's previous compact outcomes and inserts the newly calculated rows. Existing production tables are untouched.

The optional manual table-drop SQL is `sql/drop_backtest_tables_optional.sql`. It is never executed automatically.

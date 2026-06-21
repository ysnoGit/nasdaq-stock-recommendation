# Condition Backtest Lab

This directory is an isolated workspace for comparing condition groups without
requiring every screening condition to pass at once.

Registered screen types:

| ID | Conditions |
|---|---|
| `A_B` | A and B |
| `C_D` | C and D |
| `E_F` | E and F |
| `G_H` | G and H |
| `C_D_E_F` | C, D, E, and F |
| `C_D_G_H` | C, D, G, and H |

The lab owns isolated daily and weekly feature Parquets under its `tmp`
directory. They use the existing backtest's proven feature-building logic but
do not overwrite files in `backtest_lab`. The default screening range starts
on `2020-01-01`.

## Current Status

Coverage and component performance execution are implemented for all six
registered condition groups. The authoritative timing, selection-date,
deduplication, and return rules are recorded in
`docs/screening_business_logic_specification.md`.

## Commands

From the repository root:

```bash
bash condition_backtest_lab/scripts/build_features.sh
bash condition_backtest_lab/scripts/extract_sp500_benchmark.sh
bash condition_backtest_lab/scripts/list_screen_types.sh
bash condition_backtest_lab/scripts/check_environment.sh
python3 -m unittest discover -s condition_backtest_lab/tests
```

`extract_sp500_benchmark.sh` reads WRDS `comp.idx_daily` for
`gvkeyx = '000003'` (`S&P 500 Comp-Ltd`) and writes only
`condition_backtest_lab/tmp/benchmark_sp500_index.parquet`.

Run the A&B quarterly coverage study:

```bash
bash condition_backtest_lab/scripts/run_ab_coverage.sh
```

This evaluates all 300 A&B parameter combinations at every calendar-quarter
end from 2017 through 2025. Genuine zero-selection quarters are included when
at least one company has enough valid annual and quarterly history. Outputs are
written under `condition_backtest_lab/tmp/results/ab_coverage`.

The A&B ranking uses the common-window summary, which compares every
combination over the same shared quarter range. This is the only A&B summary
written to disk, so later performance tests and reports use the same top
combinations as the coverage report.

Run the C&D daily coverage study:

```bash
bash condition_backtest_lab/scripts/run_cd_coverage.sh
```

This evaluates 18 C&D parameter combinations on every eligible trading date
from the earliest complete three-month lookback through the latest local daily
feature date. It uses every company represented in daily features, counts each
`gvkey` once even when multiple issues pass, retains genuine zero-selection
dates, requires exactly 30 valid prior volume observations, and writes
security-level passing events for later performance work.

Generate the C&D coverage report after running the study:

```bash
python3 condition_backtest_lab/reports/build_cd_coverage_report.py
```

Run the E&F daily coverage study:

```bash
bash condition_backtest_lab/scripts/run_ef_coverage.sh
```

This evaluates daily MA tolerance choices 1%, 2%, and 3%. E requires complete
price-only MA20/MA50/MA100 windows and checks only pairwise clustering. F owns
the crossover check from the E row to the immediately following official
market session; a missing security row expires the setup.

Run the G&H weekly coverage study:

```bash
bash condition_backtest_lab/scripts/run_gh_coverage.sh
```

This evaluates weekly MA tolerance choices 1%, 2%, 3%, and 4% on every
eligible completed official week. G checks clustering only. H owns the full
WMA10/WMA30 crossover and must confirm on the immediately following completed
official week.

Run the combined coverage studies:

```bash
bash condition_backtest_lab/scripts/run_cdef_coverage.sh
bash condition_backtest_lab/scripts/run_cdgh_coverage.sh
python3 condition_backtest_lab/reports/build_combined_coverage_reports.py
```

C&D&E&F evaluates 54 parameter combinations on a shared daily C/D/E signal
and groups coverage on that signal date; F remains the actionable performance
date. C&D&G&H evaluates 72 combinations on every C/D daily signal date. G&H
acts as an additional AND gate only when that signal is an official completed
week-end; non-week-end dates retain the C&D result. When the weekly gate is
applied, H remains the actionable performance date.

Run the component performance study after all coverage outputs exist:

```bash
bash condition_backtest_lab/scripts/run_performance_test.sh
bash condition_backtest_lab/scripts/run_sp500_comparison.sh
```

It tests the top three coverage-ranked combinations for all six groups. For
A&B, the performance test uses the common-window coverage ranking so the
tested combinations match the A&B common-window coverage report. The other
groups use their single coverage ranking. The performance test applies the
agreed 180-calendar-day repeated-selection cooldown and writes
30/60/90/120/150/180-day outcomes under
`condition_backtest_lab/tmp/results/performance/`.

`run_sp500_comparison.sh` matches each retained performance event to the
WRDS S&P 500 total-return benchmark cache and writes benchmark/excess-return
Parquets in the same performance output directory.

Environment overrides:

```bash
export CONDITION_BACKTEST_DAILY_FEATURE_PATH="/path/to/daily_features.parquet"
export CONDITION_BACKTEST_WEEKLY_FEATURE_PATH="/path/to/weekly_features.parquet"
export CONDITION_BACKTEST_SP500_BENCHMARK_PATH="/path/to/benchmark_sp500_index.parquet"
export CONDITION_BACKTEST_START_DATE="2022-01-01"
export CONDITION_BACKTEST_END_DATE="2026-06-09"
```

`build_features.sh` reads raw market data from S3 and writes only local Parquet
files. It does not write to S3 or Supabase.

See [docs/design.md](docs/design.md) for the decisions still needed before
implementing the six screen queries.

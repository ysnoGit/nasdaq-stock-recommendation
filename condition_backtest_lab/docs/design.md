# Component Backtest Design

## Purpose

The existing backtest evaluates joined A-F and A-H screens. This lab will
evaluate smaller condition groups independently while preserving the existing
business definitions and causal timing rules for each condition.

## Reused Inputs

- Daily features: `condition_backtest_lab/tmp/daily_features.parquet`
- Weekly features: `condition_backtest_lab/tmp/weekly_features.parquet`
- Annual and quarterly fundamental growth histories: the same S3 paths used by
  `backtest_lab`

Raw S3 inputs are read-only. Feature files and results are written only under
`condition_backtest_lab/tmp` until a persistence target is explicitly chosen.
The default feature and screening window begins on `2020-01-01`.

## Timing Foundation

- A-D are evaluated using information available on the daily signal date.
- E is evaluated on the daily signal date.
- F confirms only on the same security's row on the immediately following
  official market session after E. A missing row expires the E setup.
- G is evaluated on a completed official trading week.
- H confirms only on the following completed official trading week after G.

## Fundamental Growth Definition

Annual and quarterly revenue and operating-income growth use:

`(current value - previous value) / ABS(previous value)`

All positive and negative sign transitions are evaluated. A shrinking negative
value is positive growth, a worsening negative value is negative growth, and a
negative-to-positive transition is positive growth. Growth is undefined only
when the previous value is zero, a required value is missing, or an annual
comparison year is not consecutive.

These are inherited contracts, not yet complete execution rules for every new
screen family.

## Decisions Needed Per Screen Type

1. What event anchors the screen when its group does not include E?
2. Is the result every passing event, or only the earliest event per security?
3. What is the actionable selected date and entry price?
4. Which parameters vary, and which remain fixed?
5. Which return horizons and minimum sample thresholds should be reported?
6. For `G_H`, how is the first candidate completed week chosen without a daily
   condition?
7. For `C_D_G_H`, should C/D's daily signal anchor G to the first completed
   official week on or after that signal?

Execution remains disabled until these choices are confirmed.

## C&D Coverage Contract

The C&D coverage study is implemented independently of the still-pending C&D
performance contract.

- Evaluate every available trading date.
- Use every company represented in daily features; do not apply the current
  `security_master` universe to historical research.
- Count selected companies by distinct `gvkey`. A company passes when any of
  its `(gvkey, iid)` rows passes.
- Require exactly 30 valid prior volume observations, a valid current
  `volume_ratio`, and at least three calendar months of source history for the
  security-date to be eligible.
- Include the evaluation date in Condition D's trailing three-calendar-month
  window.
- Include genuine zero-selection dates when eligible companies exist.
- Exclude dates where no company is eligible.
- Rank combinations by distance between average selected-company count and 30.
- Preserve every passing security-date for later performance analysis.

Parameter choices:

- `volume_ratio_threshold`: 4, 5, 10, 15, 20, 25
- `volume_surge_min_days`: 3, 5, 7

## E&F Coverage Contract

- Evaluate E on every eligible daily price-feature row.
- Daily MA20, MA50, and MA100 use price rows only; missing volume does not
  affect E eligibility.
- Require complete 20-, 50-, and 100-price-row moving-average windows.
- E requires only that all three pairwise MA ratios are within the selected
  tolerance.
- F owns the complete crossover check: require `MA20 <= MA50` on E and
  `MA20 > MA50` on the same security's row on the immediately following
  official market session.
- Do not recheck E clustering on F.
- Expire E when that immediately following official-session security row is
  absent.
- Count selected companies by distinct `gvkey`, retain genuine zero-selection
  dates, and rank average daily company coverage by distance from 30.
- Preserve every passing E/F security event for later performance analysis.

Parameter choices:

- `daily_ma_tolerance_pct`: 1, 2, 3

## G&H Coverage Contract

- Evaluate every eligible completed official U.S. market week as a possible G
  week.
- Weekly MAs use preceding completed weekly closes and exclude the current
  G-week close.
- Require complete WMA5, WMA10, and WMA30 windows.
- G checks only whether all three pairwise weekly MA ratios are within the
  selected tolerance.
- H owns the complete crossover: require `WMA10 <= WMA30` on G and
  `WMA10 > WMA30` on the immediately following completed official week.
- Expire G when the security has no row on that immediately following week.
- Group coverage by the G completed-week date, count distinct `gvkey`, retain
  genuine zero-selection weeks, and rank average coverage by distance from 30.
- H may fall outside an inspection window because it is supporting evidence;
  the company remains attributed to the in-window G anchor date.
- Preserve every passing G/H security event for later performance analysis.

Parameter choices:

- `weekly_ma_tolerance_pct`: 1, 2, 3, 4

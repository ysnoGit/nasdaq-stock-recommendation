# Screening Business and Timing Logic Specification

**Status:** Authoritative business-rule reference  
**Last reviewed:** 2026-06-29<br>
**Scope:** Conditions A-H, component screens, coverage studies, and backtest outcomes

## Purpose

This document records the agreed screening business rules and causal timing
rules for the project. It is the primary reference when implementing or
validating screening in the application, Supabase serving layer, production
pipeline, or a backtest.

When code and this document disagree, do not silently copy the code. Confirm
whether the code is stale, update the implementation, and add a regression
test.

## Decision Labels

- **DECIDED:** Agreed behavior that new implementations must follow.
- **CURRENT LIMITATION:** Known data or implementation limitation.
- **PENDING:** A decision is still required before implementing the affected
  workflow.
- **HISTORICAL:** Existing behavior retained only for interpreting older
  outputs.

## Core Principles

1. Screening must be causal. A condition can use only data observable by its
   evaluation or confirmation date.
2. Missing required data does not pass a condition.
3. Future confirmation values being `NULL` means the confirmation cannot be
   evaluated yet; it does not prove failure.
4. A security is identified by `(gvkey, iid)` for market-data conditions.
   Fundamentals and company coverage are identified by `gvkey`.
5. User-selectable thresholds must be applied dynamically. Stored helper flags
   based on fixed thresholds are not final screening truth.
6. Dates must describe the data actually used. Weekly dates must be real
   exchange trading sessions, including holiday-shortened weeks.
7. A market-condition candidate with close price below `$5.00` is
   automatically excluded from screening counts and selected-company lists.
8. A market-condition candidate with trading value below `$1,000,000`
   (`close price * volume`) is automatically excluded from screening counts
   and selected-company lists.

## Shared Date Definitions

| Term | Definition |
|---|---|
| Signal date | Daily trading date on which the required same-day conditions are evaluated. For joined A-F/A-H screens, this is the A-E evaluation date. |
| E date | Daily row on which Condition E is evaluated and passes. |
| F confirmation date | Row for the same `(gvkey, iid)` on the official market session immediately following E. |
| G confirmation date | First completed official trading week ending on or after the E date. |
| H confirmation date | Completed official trading week immediately following the G week. |
| Actionable selected date | First date on which every required condition for the screen is observable and has passed. |
| Evaluation date | Calendar-quarter end used by the A&B coverage study. |
| Inspection window | Inclusive user-requested range of inspection anchor dates for which company counts are requested. Supporting causal history and required future confirmations may fall outside this range. |
| Inspection anchor date | Date to which a screening count belongs. This date must be inside the inspection window; supporting dates do not have to be. |
| Standalone G&H setup date | Completed official week-end date on which G is evaluated. It is the inspection anchor date for standalone G&H; H is checked on the following completed week. |
| Official week end | Final actual U.S. exchange trading session of a calendar week. Usually Friday, but earlier when Friday is a holiday. |
| Data-as-of date | Date through which source data was available when an output was built. It is not a weekly partition key or confirmation date. |

The official U.S. exchange calendar must be used for weekly logic. The current
calendar utility prefers XNAS and falls back to XNYS.

### Inspection-Window Semantics for Conditions C-H

**DECIDED**

The inspection window limits only the inspection anchor dates whose company
counts are requested. It does not truncate the supporting data needed to
evaluate those anchor dates:

- C&D uses the shared C/D daily evaluation date as its inspection anchor.
- E&F uses the E setup date as its inspection anchor. F is checked on the
  immediately following official session, even when that session is after the
  inspection-window end.
- Standalone G&H uses the completed G setup week as its inspection anchor. H
  is checked on the immediately following completed official week, even when
  that week is after the inspection-window end.
- C&D&E&F uses the shared C/D/E daily signal date as its inspection anchor.
- C&D&G&H uses the C/D daily signal date as its inspection anchor. On ordinary
  trading dates it evaluates C&D only. When the anchor is the official week
  end, G&H becomes an additional AND gate.
- A Daily Price + Weekly Price E&F&G&H screen uses the E date as its inspection
  anchor and checks F on the next official session. On ordinary trading dates
  it evaluates E&F only. When E is the official week end, G&H becomes an
  additional AND gate.
- Joined A-H uses its A-E daily signal date as the inspection anchor for
  screening counts while retaining its separately defined actionable date.

Historical rows before the start and required confirmation rows after the end
may be used when they are causally required to evaluate an anchor date inside
the window. A candidate whose anchor date is outside the inspection window is
not included merely because one of its supporting dates falls inside it.

The inspection-count date and actionable selected date are intentionally
different for screens requiring F or H. Counts and chart points belong to the
inspection anchor date. Entry timing and performance measurement begin only
on the actionable confirmation date after every required condition is known.

When a required future confirmation row is not yet available as of the data
snapshot, the candidate is pending/not evaluable. It must not be treated as a
confirmed pass or a confirmed failure.

### Market Liquidity Eligibility

**DECIDED**

Market-condition screening results apply a fixed `$5.00` minimum close price
filter and a fixed `$1,000,000` minimum trading-value filter before counting or
displaying companies:

- Market-condition screens use the close price on the inspection anchor row.
  For standalone weekly screens, this is the weekly close price for the G setup
  week.
- Trading value is `close price * volume` on the same candidate row. For
  standalone weekly screens, this uses weekly close price and weekly volume.
- Market candidates below either liquidity floor are not counted in chart
  points and do not appear in the selected-company table.

The price and trading-value floors are currently fixed, not user-selectable.
Fundamental-only screens do not apply these liquidity filters until a historical
quarter-end price serving table is available.

### Mixed-Frequency G&H Gate

**DECIDED**

When G&H is combined with conditions evaluated at daily grain, do not force a
weekly result onto every daily inspection anchor:

1. Determine whether the daily inspection anchor is the official final U.S.
   exchange session of its calendar week.
2. On a non-week-end trading date, evaluate and count companies using the
   selected non-weekly conditions only. G&H is not evaluated and the count is
   not zero merely because no weekly result exists.
3. On an official week-end trading date, evaluate the non-weekly conditions
   and apply G&H as an additional AND condition for the same securities.
4. Use the immediately following completed official week to check H. That H
   row may be after the inspection-window end because the count remains
   attributed to the in-window week-end anchor.
5. A holiday-shortened Thursday is a week-end anchor when the exchange is
   closed on Friday. Missing security data must not be used to infer the end
   of a week; use the official exchange calendar.

Example for E&F combined with G&H:

- Monday through Thursday inspection anchors: count E&F passes.
- Friday inspection anchor, or Thursday in a Friday-holiday week: count only
  securities passing E&F and G&H.

Fundamental-only A&B screening is different: it uses the selected end date as
its evaluation date and does not require a start date. If fundamentals are
ever joined with C-H, the inspection-anchor semantics above still apply to the
market-condition screening counts.

## Source Data and Grain

| Dataset | Intended grain | Main use |
|---|---|---|
| Annual fundamental growth history | One row per `(gvkey, fyear)` | Condition A |
| Quarterly fundamental growth history | One row per `(gvkey, fyearq, fqtr)` | Condition B |
| Daily market features | One row per `(gvkey, iid, snapshot_date)` | Conditions C-F and daily prices |
| Weekly market features | One row per `(gvkey, iid, official week)` | Conditions G-H |
| Security master | One row per `(gvkey, iid)` | Display and universe filtering |

Current production S3 locations use bucket
`s3://nasdaq-stock-recommendation/`:

| Dataset | Current location |
|---|---|
| Raw annual fundamentals | `raw/compustat_annual/latest/compustat_annual.parquet` |
| Raw quarterly fundamentals | `raw/compustat_quarterly/latest/compustat_quarterly.parquet` |
| Annual growth history | `processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet` |
| Quarterly growth history | `processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet` |
| Daily market features | `processed/daily_market_metrics/` |
| Weekly market features | `processed/weekly_market_metrics/` |

The reusable full-screen backtest stores local daily and weekly feature
Parquets under `backtest_lab/tmp/`. The component backtest lab stores its
isolated copies and outputs under `condition_backtest_lab/tmp/`. Both labs read
the production fundamental growth histories from S3.

Annual and quarterly inputs are deduplicated before growth calculation:

- Annual: retain the latest `datadate` for each `(gvkey, fyear)`.
- Quarterly: retain the latest `datadate` for each
  `(gvkey, fyearq, fqtr)`.

## Fundamental Growth Definition

Annual and quarterly revenue and operating-income growth use:

```text
growth = (current value - previous value) / ABS(previous value)
```

This signed-denominator rule handles positive and negative values consistently:

| Previous | Current | Interpretation |
|---:|---:|---|
| Positive | Larger positive | Positive growth |
| Positive | Smaller positive or negative | Negative growth |
| Negative | Less negative or positive | Positive growth |
| Negative | More negative | Negative growth |
| Zero | Any value | Undefined |

Growth is `NULL` when the previous value is zero, either required value is
missing, or the required comparison period is unavailable.

Annual growth compares a fiscal year only with the immediately preceding
fiscal year. Quarterly growth is year-over-year and compares a fiscal quarter
with the same fiscal quarter in the preceding fiscal year.

## Condition Rules

### Condition A: Annual Growth

**DECIDED**

Parameters:

- `annual_growth_pct`
- `annual_years`

At the evaluation date:

1. Use only annual records with `datadate <= evaluation date`.
2. Rank all available fiscal-year records before filtering invalid growth
   rows.
3. Take the latest requested `annual_years`.
4. Require the selected fiscal years to be consecutive.
5. Require both annual revenue growth and annual operating-income growth to be
   non-null and at least `annual_growth_pct` in every selected fiscal year.

Condition A passes only if the entire latest requested block passes. A missing
or invalid latest period cannot be skipped in favor of an older valid period.

### Condition B: Quarterly Growth

**DECIDED**

Parameters:

- `quarterly_growth_pct`
- `quarter_count`

At the evaluation date:

1. Use only quarterly records with `datadate <= evaluation date`.
2. Rank all available fiscal-quarter records before filtering invalid growth
   rows.
3. Take the latest requested `quarter_count`.
4. Require the selected fiscal quarters to be consecutive across fiscal-year
   boundaries.
5. Require both quarterly revenue growth and quarterly operating-income growth
   to be non-null and at least `quarterly_growth_pct` in every selected fiscal
   quarter.

Condition B passes only if the entire latest requested block passes. A missing
or invalid latest period cannot be skipped.

### Production Fundamental Inspection

**DECIDED**

The production application exposes Condition A and Condition B as separate,
mutually exclusive screens. Neither fundamental screen can be combined with
Conditions C-H. The two screens share a dedicated calendar-quarter inspection
control that is independent of the daily market inspection window.

The user selects an **Inspection through** year and quarter. The default is the
completed calendar quarter immediately preceding the current calendar quarter.
The chart then moves backward by the selected number of inspection periods.
Annual and quarterly inspection periods default to four and remain separate
from `annual_years` and `quarter_count`, which control condition lookback.

Every requested calendar quarter is returned. A quarter without the relevant
source records is displayed as zero with an internal `no_data` status; it is
not skipped or replaced by an older quarter.

For the Annual Fundamental screen:

1. A chart point represents a calendar quarter.
2. Candidate companies are those with an annual fiscal-year record whose
   `datadate` falls inside that calendar quarter. This means the company's full
   fiscal year ended during the chart quarter.
3. When more than one annual record exists for a company in the bucket, use
   the latest `datadate` in that bucket as the candidate endpoint.
4. Evaluate Condition A using that fiscal year and its required immediately
   preceding consecutive fiscal years.

For the Quarterly Fundamental screen:

1. A chart point represents a calendar quarter.
2. Candidate companies are those with a fiscal-quarter record whose `datadate`
   falls inside that calendar quarter.
3. When more than one quarterly record exists for a company in the bucket, use
   the latest `datadate` in that bucket as the candidate endpoint.
4. Evaluate Condition B using that fiscal quarter and its required immediately
   preceding consecutive fiscal quarters.

Calendar quarters group chart results; they do not rename company fiscal
periods. For example, a fiscal Q1 ending October 31 belongs to the calendar Q4
chart bucket but remains fiscal Q1 for consecutiveness and year-over-year
growth calculation.

### Fundamental Availability Timing

**CURRENT LIMITATION**

Current processed fundamentals contain `datadate`, but not the filing or
publication date on which the information became public. Existing research
limits fundamentals to `datadate <= evaluation date`. This reduces, but does
not eliminate, look-ahead risk.

The production application should use filing/publication availability dates
when they become available. Until then, reports must disclose this limitation.

### Condition C: Current Volume Surge

**DECIDED**

Parameter:

- `volume_ratio_threshold`

Daily features calculate:

```text
volume_ma30 = average volume of exactly 30 preceding valid trading rows,
              excluding the current row
volume_ratio = current volume / volume_ma30
```

`volume_ma30` and `volume_ratio` remain `NULL` until all 30 prior valid-volume
rows exist.

Condition C passes on the signal date when:

```text
volume_ratio >= volume_ratio_threshold
```

Missing or zero `volume_ma30` produces no valid ratio and cannot pass.

### Condition D: Repeated Recent Volume Surges

**DECIDED**

Parameters:

- `volume_ratio_threshold`
- `volume_surge_min_days`

Count daily rows for the same `(gvkey, iid)` from the signal date minus three
calendar months through the signal date, inclusive, where:

```text
volume_ratio >= volume_ratio_threshold
```

Condition D passes when the count is at least `volume_surge_min_days`.
Condition D must be calculated dynamically because both parameters are
user-selectable.

### Condition E: Daily Moving-Average Setup

**DECIDED**

Parameter:

- `daily_ma_tolerance_pct`

Daily MA20, MA50, and MA100 are calculated from adjusted close, including the
current daily row. Each moving average remains `NULL` until its complete valid
price window exists: 20 rows for MA20, 50 for MA50, and 100 for MA100. On the
E date:

Missing volume does not make an otherwise valid price row ineligible for these
moving averages.

1. MA20, MA50, and MA100 must all exist.
2. Every pair must be within the selected tolerance:

```text
MA20 / MA50 within 1 +/- tolerance
MA20 / MA100 within 1 +/- tolerance
MA50 / MA100 within 1 +/- tolerance
```

E does not check MA20/MA50 orientation. That before-and-after orientation is
owned entirely by F.

### Condition F: Next-Trading-Day Daily Crossover

**DECIDED**

F is not another clustering check. It confirms that the crossover occurs after
E has passed.

1. Use the row for the same `(gvkey, iid)` on the immediately following
   official U.S. equity market session, not simply the next calendar day or a
   later available security row.
2. On E, require `MA20 <= MA50`.
3. On the next trading row, require `MA20 > MA50`.
4. The future row, confirmation date, and required future values must exist.

F confirmation does not require E's clustering ratios to remain within
tolerance on the confirmation row. If the security has no row on the
immediately following official session, the E setup expires and cannot be
confirmed by a later row.

### Condition G: Weekly Moving-Average Setup

**DECIDED FOR JOINED A-H**

Parameter:

- `weekly_ma_tolerance_pct`

G is evaluated using the first completed official trading week ending on or
after the E date. G depends on E timing, not F timing.

- If E occurs on an official week-end trading session, that completed week can
  be used for G.
- If E occurs midweek, wait until the current calendar week completes. Do not
  use the preceding completed week.

On the G week:

1. WMA5, WMA10, and WMA30 must all exist.
2. Every pair must be within the selected tolerance.
G does not check WMA10/WMA30 orientation. That before-and-after orientation is
owned entirely by H.

**Implementation detail to preserve:** the current reusable backtest feature
builder calculates weekly MAs from preceding completed weekly closes,
excluding the current week's close. Each WMA remains undefined until its
complete 5-, 10-, or 30-week window exists.

### Condition H: Following-Week Weekly Crossover

**DECIDED FOR JOINED A-H**

H is not another clustering check.

1. Use the completed official trading week immediately following G.
2. On G, require `WMA10 <= WMA30`.
3. On the following completed week, require `WMA10 > WMA30`.
4. The following weekly row, confirmation date, and required future values must
   exist.

H confirmation does not require G's clustering ratios to remain within
tolerance on the following week.

## Joined Screen Timing

### A-F

The joined A-F sequence is:

1. Evaluate A-E on the daily signal date.
2. Evaluate F on the immediately following official market session.
3. If all conditions pass, the actionable selected date is the F confirmation
   date.
4. The entry price is the adjusted close on the F confirmation date, falling
   back to raw close only when adjusted close is unavailable.

### A-H

The joined A-H sequence is:

1. Evaluate A-E on the daily signal date.
2. Evaluate F on the immediately following official market session.
3. Evaluate G on the first completed official trading week ending on or after
   E, independently of F timing.
4. Evaluate H on the completed official week immediately following G.
5. If all conditions pass, the actionable selected date is the later of the F
   and H confirmation dates. This is normally the H confirmation date.
6. Use the price observable on the actionable selected date. Under the current
   backtest, this is normally the H-confirmation weekly close.

The joined A-H screen does not require A-E to pass again on the G or H date.

## Component Screen Families

The component backtest lab registers:

- A&B
- C&D
- E&F
- G&H
- C&D&E&F
- C&D&G&H

**DECIDED FOR COMPONENT COVERAGE AND PERFORMANCE STUDIES**

| Group | Actionable selection date |
|---|---|
| A&B | Calendar-quarter evaluation date |
| C&D | C&D daily signal date |
| E&F | F confirmation date |
| G&H | H confirmation official week-end date |
| C&D&E&F | F confirmation date |
| C&D&G&H | H confirmation official week-end date |

Screening coverage and application charts use different dates from the
actionable dates above:

| Group | Inspection-count anchor date |
|---|---|
| A&B | Selected fundamental evaluation/end date |
| C&D | C/D daily evaluation date |
| E&F | E setup date |
| G&H | G setup official week-end date |
| C&D&E&F | Shared C/D/E daily signal date |
| C&D&G&H | C/D daily signal date |
| E&F&G&H | E setup date |

For A&B, which selects at company grain, map each selected company to one
tradable security by preferring a matching ticker, then `iid = '01'`, then the
security with the deepest available daily price history.

### Standalone G&H Inspection-Window Timing

**DECIDED**

For a standalone G&H screen, apply the inclusive inspection window to the
**G setup date**, which is the inspection anchor date. The H confirmation date
may be outside the inspection window.

1. Enumerate completed official G weeks whose `g_date` falls inside the
   requested inspection window.
2. Evaluate G on each included `g_date` using that week's WMA5, WMA10, and
   WMA30 values and the selected weekly tolerance.
3. Evaluate H on the completed official week immediately following G.
4. Use the required H date even when it falls after the inspection-window end.
5. Attribute the screening count and chart point to G, the inspection anchor
   date.
6. The actionable selected date for entry/performance remains the H
   confirmation official week-end date because G&H is not fully observable
   until H.

Example for an inspection window of `2026-05-01` through `2026-05-31`:

| Included G setup/count date | Required H confirmation/actionable date |
|---|---|
| 2026-05-01 | 2026-05-08 |
| 2026-05-08 | 2026-05-15 |
| 2026-05-15 | 2026-05-22 |
| 2026-05-22 | 2026-05-29 |
| 2026-05-29 | 2026-06-05 |

The `2026-04-24` G setup is excluded even though its H date is `2026-05-01`.
The `2026-05-29` G setup is included and its pass/fail result is counted on
`2026-05-29`, using H data from `2026-06-05`.

The G-to-H pairing above describes the standalone G&H screen. Joined A-H and
C&D&G&H retain their separately defined daily inspection anchors and G-mapping
rules. Their future confirmations may also fall outside the inspection window
when required to evaluate an in-window anchor date.

## A&B Coverage Study

**DECIDED**

The A&B coverage study:

- Uses the configured study range from `2017-01-01` through `2025-12-31` and
  evaluates every calendar-quarter end in that range.
- Counts companies by distinct `gvkey`.
- Includes genuine zero-selection quarters when at least one company is
  evaluable for the parameter combination.
- Excludes only quarters with no evaluable companies due to insufficient
  required history.
- Uses the consecutive, fully valid latest-period rules defined for A and B.
- Targets an average of 30 selected companies.

The common-window comparison begins at the latest first-evaluable quarter
among all compared parameter combinations, so every combination is averaged
over the same quarter range.

Confirmed A&B coverage parameter choices:

| Parameter | Choices |
|---|---|
| `annual_growth_pct` | 3, 5, 10, 15, 20 |
| `annual_years` | 2, 3, 4 |
| `quarterly_growth_pct` | 3, 5, 10, 15, 20 |
| `quarter_count` | 2, 3, 4, 5 |

This creates 300 A&B parameter combinations.

## C&D Coverage Study

**DECIDED**

The C&D coverage study:

- Evaluates every available trading date from the earliest eligible date
  through the latest daily feature date.
- Uses every company represented in the historical daily feature dataset.
  It does not apply the current `security_master` universe to historical
  research.
- Counts companies by distinct `gvkey`. A company passes when any of its
  `(gvkey, iid)` security rows passes.
- Requires exactly 30 valid prior volume observations, a valid current
  `volume_ratio`, and daily source history reaching at least three calendar
  months before the evaluation date.
- Includes the evaluation date in Condition D's trailing three-calendar-month
  window.
- Includes genuine zero-selection trading dates when at least one company is
  eligible.
- Excludes only dates where no company is eligible.
- Ranks combinations by
  `ABS(average selected company count - 30)`.
- Preserves every passing `(parameter, evaluation date, gvkey, iid)` event for
  future performance analysis.

Confirmed C&D coverage parameter choices:

| Parameter | Choices |
|---|---|
| `volume_ratio_threshold` | 4, 5, 7, 10, 15, 20, 25 |
| `volume_surge_min_days` | 2, 3, 4, 5, 7 |

This creates 35 C&D parameter combinations.

The production application will use `security_master` for its current serving
universe even though the historical coverage and performance studies do not.

## Historical Full-Screen Parameter Grid

**HISTORICAL**

The existing full A-F/A-H backtest grid contains 192 combinations:

| Parameter | Historical choices |
|---|---|
| `annual_growth_pct` | 5, 10 |
| `quarterly_growth_pct` | 5, 10 |
| `annual_years` | 2, 3 |
| `quarter_count` | 2, 3, 4 |
| `volume_ratio_threshold` | 2, 3, 4, 5 |
| `volume_surge_min_days` | 2, 3 |
| `daily_ma_tolerance_pct` | fixed at 1 |
| `weekly_ma_tolerance_pct` | fixed at 2 |

These choices describe existing reports; they are not automatically the final
application choices.

## Backtest Selection Retention

**HISTORICAL**

The existing joined A-F/A-H backtest retains only the earliest completed
selection per `(parameter set, screen type, gvkey, iid)`. This avoids repeatedly
counting the same security in that study.

**DECIDED FOR COMPONENT PERFORMANCE STUDIES**

Component performance studies apply a 180-calendar-day cooldown independently
for each `(parameter combination, gvkey, iid)`:

1. Retain the earliest passing event.
2. Suppress additional passing events for the same parameter combination and
   security during the next 180 calendar days.
3. After the cooldown has elapsed, retain the next passing event as a new
   selection and begin a new 180-calendar-day cooldown from that retained
   event.
4. Different parameter combinations are evaluated independently, even when
   they select the same security on the same date.

This rule prevents dense clusters of repeated signals from one security from
dominating performance averages while still allowing that security to become
a later independent selection.

**DECIDED FOR THE PRODUCTION APPLICATION**

The interactive application evaluates every inspection anchor independently.
A company may appear on multiple inspection dates when it passes on each date.
Each date counts a `gvkey` at most once, and the application does not apply the
backtest's 180-day cooldown.

## Production Serving Decisions

**DECIDED**

- Browser clients call tightly controlled `SECURITY DEFINER` Supabase RPCs.
  Direct table access remains blocked by RLS.
- Anonymous visitors may execute the screening RPCs.
- Chart counts use distinct `gvkey` companies. Detail results retain one
  passing security per company, preferring `iid = '01'` and then the most
  recently observed security.
- Fundamental-only identity comes from `company_master`; market-condition
  identity comes from `security_master`.
- Pending F or H confirmation is returned explicitly and is never represented
  as a zero-company result.
- Current `security_master.is_active` is not used for historical screening.
  The optional explicit universe-exclusion filter defaults to off.

## Entry Price and Return Outcomes

**DECIDED FOR CURRENT BACKTEST REPORTS**

Daily adjusted price is:

1. Existing adjusted close when available.
2. Otherwise raw close divided by a nonzero adjustment factor.
3. Otherwise raw close.

For each retained selection:

- Return measurement starts at the actionable selected date and selected entry
  price.
- Six-month, one-year, and two-year horizon prices use the first available
  trading price on or after the calendar horizon.
- A horizon return is:

```text
(horizon adjusted price / selected entry price - 1) * 100
```

- A performance result is included only when the entry price and required
  horizon price exist and the entry price is nonzero.

Coverage and performance answer different questions. A selection may count
toward coverage even when a later performance horizon is not yet observable.

## Component Performance Study

**DECIDED**

The component performance study:

- Tests the top three coverage-ranked parameter combinations for each group.
- Applies the 180-calendar-day repeated-selection cooldown defined above.
- Measures returns after 30, 60, 90, 120, 150, and 180 calendar days from the
  actionable selection date.
- Uses the first available daily adjusted close on or after the actionable
  selection date as entry price.
- Uses the first available daily adjusted close on or after each calendar
  horizon as horizon price.
- Calculates each horizon independently and excludes an event only from a
  horizon whose future price is not observable.
- Does not impose a common final selection date across component groups.
- Reports average return, median return, win rate, standard deviation, range,
  completed observations, and unique-company counts.

Average returns must be interpreted alongside median returns and win rates.
Extreme historical price observations can heavily distort the arithmetic
mean.

## Production and Serving-Layer Rules

**DECIDED**

- The active production pipeline builds processed features and loads serving
  data. It does not need to persist one fixed final screening-results file.
- Final conditions should be evaluated dynamically from user-selected
  parameters.
- Condition D must use retained daily `volume_ratio` history.
- Stored `daily_f_confirmation_pass` and `weekly_h_confirmation_pass` fields
  must not be treated as final truth.
- Stored future-input fields may be used to evaluate F/H dynamically:
  `future_daily_*`, `daily_f_confirmed_using_date`, `future_weekly_*`, and
  `weekly_h_confirmed_using_date`.
- Fixed-threshold `flag_e`, `flag_f`, `flag_g`, and `flag_h` fields produced by
  feature builders are helper/audit fields only.

## Known Implementation Gaps

| Area | Status | Required action |
|---|---|---|
| Older joined A-F/A-H fundamental query | It filters invalid growth rows before selecting the latest lookback, so it can skip a missing latest period. | Align it with the consecutive, fully valid latest-period A/B rules before relying on a new full-screen run. |
| Production helper E/G flags | They check clustering with fixed tolerances. | Recalculate official E/G dynamically when using user-selected tolerances. |
| Production helper F/H flags | They are fixed-threshold helper flags. | Recalculate official crossover conditions dynamically from current and future input values. |
| Windowed C-H consumers | Implemented in the component backtest for E&F, G&H, C&D&E&F, and C&D&G&H. Production/application consumers still need the same treatment. | Filter and group screening counts by the group-specific inspection anchor date. Continue using required past/future supporting rows, and preserve F/H as actionable dates for entry/performance. |
| Mixed-frequency combined screens | Implemented for the component C&D&G&H backtest. Production/application consumers still need the same gate. | Apply G&H only when the daily inspection anchor is the official week-end. On other trading dates, retain the result from the selected non-weekly conditions. |
| Fundamental availability | Filing/publication dates are absent. | Add availability dates before claiming a fully look-ahead-safe production screen. |
| Component performance studies | Entry, retention, and performance-comparison rules remain incomplete. | Resolve them before implementing component performance tests. |

## Minimum Validation Cases

Every implementation of these rules should include tests for:

1. A passes only when every latest requested consecutive fiscal year passes.
2. B passes only when every latest requested consecutive fiscal quarter passes.
3. An invalid latest A/B period is not replaced by an older valid period.
4. Positive-to-negative, negative-to-positive, improving-negative, and
   worsening-negative growth cases use the signed-denominator formula.
5. A zero previous fundamental value produces undefined growth.
6. C uses a 30-row prior-volume average that excludes the current row.
7. D includes the signal date and exactly the trailing three-calendar-month
   window.
8. F uses the immediately following official market session and requires the
   MA20/MA50 crossover; a missing security row cannot be replaced by a later
   row.
9. Friday E uses that Friday for G when it is the official week end.
10. Midweek E waits for that week's official completion for G.
11. A holiday-shortened week uses the actual final trading session.
12. H uses the completed weekly row immediately following G and requires the
    WMA10/WMA30 crossover.
13. C&D counts are attributed to the C/D daily inspection anchor date.
14. E&F counts are attributed to E, including when the required F session is
    after the inspection-window end.
15. G&H counts are attributed to G, including when the required H week is
    after the inspection-window end.
16. Joined C-H screens filter and group counts by their defined daily or weekly
    inspection anchor, not by their later actionable confirmation date.
17. A candidate anchored outside the window is excluded even if a supporting
    setup or confirmation date is inside the window.
18. Pre-window history and post-window confirmation rows remain available when
    causally required to evaluate an in-window anchor date.
19. A combined daily-plus-G&H screen returns the non-weekly condition count on
    non-week-end trading dates rather than zero or not-applicable.
20. The same combined screen applies G&H as an additional AND gate only on the
    official week-end inspection anchor.
21. Missing future rows leave F/H pending or not evaluable; they do not pass.
22. A-F return measurement starts on F.
23. A-H return measurement starts only after both F and H are observable.
24. Horizon prices use the first available trading session on or after each
    calendar horizon.

## Implementation Map

| Concern | Current reference |
|---|---|
| Production fundamental growth builder | `server_pipeline/fundamentals/build_fundamental_growth_history_s3.py` |
| Consecutive A&B coverage implementation | `condition_backtest_lab/src/ab_coverage.py` |
| Joined A-F/A-H screening implementation | `backtest_lab/src/screening_logic.py` |
| Reusable backtest daily/weekly feature builder | `backtest_lab/src/storage.py` |
| Backtest horizon outcome calculation | `backtest_lab/src/price_outcome.py` |
| Official week-end calendar | `server_pipeline/utils/trading_calendar.py` |
| Supabase future-confirmation input builder | `server_pipeline/serving/load_processed_features_to_supabase.py` |
| Component-screen open decisions | `condition_backtest_lab/docs/design.md` |

## Change Control

When changing a condition:

1. Update this document first or in the same change.
2. State whether the change affects business meaning, timing, parameters,
   feature generation, entry price, or return calculation.
3. Add or update causal-timing and edge-case tests.
4. Rebuild affected processed data.
5. Rerun affected coverage/backtest outputs.
6. Regenerate reports and label them with the logic version or generation
   date.
7. Confirm that application, Supabase, production, and backtest logic have not
   drifted apart.

## Decision Log

| Date | Decision |
|---|---|
| 2026-06-14 | Treat the consecutive, fully valid latest-period rule as authoritative for A and B. |
| 2026-06-14 | Use signed-denominator growth so improving negative fundamentals can count as growth; previous zero remains undefined. |
| 2026-06-14 | Keep the current `datadate <= evaluation date` rule for research while documenting the filing-availability limitation. |
| 2026-06-14 | F must confirm an MA20-over-MA50 crossover on the next trading row after E. |
| 2026-06-14 | G timing depends on E, not F; midweek E waits for the current week's official completion. |
| 2026-06-14 | H must confirm a WMA10-over-WMA30 crossover on the completed week immediately following G. |
| 2026-06-14 | Keep coverage and observable performance as separate concepts. |
| 2026-06-15 | Apply a 180-calendar-day repeated-selection cooldown per `(parameter combination, gvkey, iid)` in component performance studies. |
| 2026-06-15 | Component performance tests use the top three coverage combinations per group and measure 30–180 calendar-day returns without a common group end date. |
| 2026-06-14 | Preserve unresolved component-screen timing choices as explicit pending decisions. |
| 2026-06-14 | C&D coverage evaluates every eligible trading date, uses all companies represented in daily features, counts distinct `gvkey`, and targets an average of 30 selections across the configured parameter grid. |
| 2026-06-14 | Historical C&D coverage does not apply current `security_master` filtering; the production application will use `security_master`. |
| 2026-06-14 | Added `4` as a C&D `volume_ratio_threshold` coverage-study choice. |
| 2026-06-29 | Added `7` as a C&D `volume_ratio_threshold` application choice. |
| 2026-06-29 | Added `2` and `4` as C&D `volume_surge_min_days` application choices. |
| 2026-06-15 | Daily MA20/MA50/MA100 remain undefined until their complete 20/50/100 valid-price windows exist; incomplete-window securities are not eligible for E/F. |
| 2026-06-15 | `volume_ma30` and `volume_ratio` remain undefined until exactly 30 valid prior-volume rows exist; incomplete-window securities are not eligible for C/D. |
| 2026-06-15 | Daily MAs depend only on valid price rows; missing volume does not affect E/F eligibility. |
| 2026-06-15 | F is crossover-only on the immediately following official market session; an absent security row expires E rather than allowing a later confirmation. |
| 2026-06-15 | H is crossover-only and does not recheck G clustering on its confirmation week. |
| 2026-06-15 | E and G check clustering only; F and H own both the before and after orientation required to prove their respective crossovers. |
| 2026-06-15 | Standalone G&H evaluates every eligible completed official week, groups coverage on H confirmation, and expires G when the immediately following company-week is absent. |
| 2026-06-15 | WMA5/WMA10/WMA30 use preceding completed weekly closes and require complete 5/10/30-week windows. |
| 2026-06-15 | C&D&E&F shares a daily C/D/E signal and groups coverage on next-session F confirmation. |
| 2026-06-15 | C&D&G&H maps each C/D daily signal to the first completed official G week ending on or after it and groups coverage on following-week H confirmation. |
| 2026-06-19 | Refined: standalone G&H initially allowed H after the window but did not yet distinguish the G inspection-count date from the H actionable date. |
| 2026-06-19 | Superseded: the inspection window was briefly treated as a strict boundary for every C-H supporting and confirmation date. |
| 2026-06-19 | The inspection window limits screening-count anchor dates only. Required causal history and future F/H confirmations may lie outside it; counts remain attributed to the in-window anchor, while entry/performance begins on the later actionable date. Fundamental-only A&B uses the end date without requiring a start date. |
| 2026-06-19 | In mixed-frequency screens, G&H is an additional AND gate only on official week-end inspection anchors. Non-week-end dates retain the count from the selected non-weekly conditions. |
| 2026-06-20 | Updated component backtests so E&F counts on E, G&H counts on G, C&D&E&F counts on the shared signal date, and C&D&G&H counts on each C/D daily anchor while applying G&H only at official week ends. F/H remain actionable performance dates. |

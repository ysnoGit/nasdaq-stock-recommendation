# Backtesting Plan

## Goal

Evaluate A-F and A-H independently from January 1, 2022 through the latest available daily price date across 192 parameter combinations.

Selections use causal confirmation timing:

- `signal_date` is the daily row where A-E first pass.
- A-F becomes actionable on `f_confirmation_date`, the next trading row. Its
  `selected_date`, entry price, and return measurement begin on that date.
- For A-H, the A-E signal is carried forward to the first completed official
  trading week on or after `signal_date` for G. H uses the following completed
  weekly row. Its `selected_date`, entry price, and return measurement begin on
  `h_confirmation_date`.
- A-H does not require A-E to pass again on the G confirmation week end.

For each parameter set, screen type, and security, retain only the first signal
that completes the required confirmations. Then summarize price performance
from the actionable `selected_date` through the latest available date.

## Conditions

- A: latest valid annual rows meet the selected annual threshold for the selected number of years.
- B: latest valid quarterly rows meet the selected quarterly threshold for the selected number of quarters.
- C: selected-date volume ratio meets the threshold.
- D: enough threshold-meeting volume-ratio days exist in the trailing three months.
- E/F: current and next-daily MA20/MA50/MA100 ratios are within 1%.
- G/H: current and next-weekly MA5/MA10/MA30 ratios are within 2%.
- A-H evaluates G at the first completed official weekly end on or after the
  original daily signal date, then evaluates H using the following completed
  official weekly row.

Null future values do not pass F or H.

## Fundamentals Availability Limitation

The processed annual and quarterly growth histories contain `datadate`, but not
the date when the filing became publicly available. The prototype limits rows
to `datadate <= signal_date`, which reduces look-ahead bias but does not fully
eliminate it. A production-grade research version should use filing/publication
availability dates.

## Price Outcome

Price outcome uses adjusted close when available and falls back to close. A-F
uses the F-confirmation daily close as its entry price. A-H uses the
H-confirmation weekly close as its entry price. It records latest, high, low,
earliest high/low dates, total return, maximum return, drawdown, and trading-day
count beginning on the actionable selection date.

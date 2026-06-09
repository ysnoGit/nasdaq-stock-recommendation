# Backtesting Plan

## Goal

Evaluate A-F and A-H independently from January 1, 2022 through the latest available daily price date across 192 parameter combinations.

For each parameter set, screen type, and security, retain only the first passing date. Then summarize price performance from that date through the latest available date.

## Conditions

- A: latest valid annual rows meet the selected annual threshold for the selected number of years.
- B: latest valid quarterly rows meet the selected quarterly threshold for the selected number of quarters.
- C: selected-date volume ratio meets the threshold.
- D: enough threshold-meeting volume-ratio days exist in the trailing three months.
- E/F: current and next-daily MA20/MA50/MA100 ratios are within 1%.
- G/H: current and next-weekly MA5/MA10/MA30 ratios are within 2%.
- A-H is evaluated only when the daily selected date equals a completed official weekly end date.

Null future values do not pass F or H.

## Fundamentals Availability Limitation

The processed annual and quarterly growth histories contain `datadate`, but not the date when the filing became publicly available. The prototype limits rows to `datadate <= selected_date`, which reduces look-ahead bias but does not fully eliminate it. A production-grade research version should use filing/publication availability dates.

## Price Outcome

Price outcome uses adjusted close when available and falls back to close. It records latest, high, low, earliest high/low dates, total return, maximum return, drawdown, and trading-day count after selection.

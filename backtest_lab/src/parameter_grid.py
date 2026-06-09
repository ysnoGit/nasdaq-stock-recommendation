from __future__ import annotations

from itertools import product

import pandas as pd


ANNUAL_GROWTH_PCT = [2, 3]
QUARTERLY_GROWTH_PCT = [2, 3]
ANNUAL_YEARS = [2, 3]
QUARTER_COUNTS = [2, 3, 4]
VOLUME_RATIO_THRESHOLDS = [2, 3, 4, 5]
VOLUME_SURGE_MIN_DAYS = [2, 3]
DAILY_MA_TOLERANCE_PCT = 1
WEEKLY_MA_TOLERANCE_PCT = 2


def build_parameter_grid(start_date: str, end_date: str | None) -> pd.DataFrame:
    rows = []
    for values in product(
        ANNUAL_GROWTH_PCT,
        QUARTERLY_GROWTH_PCT,
        ANNUAL_YEARS,
        QUARTER_COUNTS,
        VOLUME_RATIO_THRESHOLDS,
        VOLUME_SURGE_MIN_DAYS,
    ):
        annual_pct, quarterly_pct, annual_years, quarter_count, volume_ratio, surge_days = values
        rows.append(
            {
                "parameter_set_name": (
                    f"ag{annual_pct}_qg{quarterly_pct}_ay{annual_years}"
                    f"_qc{quarter_count}_vr{volume_ratio}_vd{surge_days}"
                ),
                "start_date": start_date,
                "end_date": end_date,
                "annual_growth_pct": annual_pct,
                "quarterly_growth_pct": quarterly_pct,
                "annual_years": annual_years,
                "quarter_count": quarter_count,
                "volume_ratio_threshold": volume_ratio,
                "volume_surge_min_days": surge_days,
                "daily_ma_tolerance_pct": DAILY_MA_TOLERANCE_PCT,
                "weekly_ma_tolerance_pct": WEEKLY_MA_TOLERANCE_PCT,
            }
        )
    grid = pd.DataFrame(rows)
    if len(grid) != 192:
        raise RuntimeError(f"Expected 192 parameter combinations, built {len(grid)}.")
    return grid

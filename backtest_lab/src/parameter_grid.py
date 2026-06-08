from __future__ import annotations

from dataclasses import dataclass


ANNUAL_GROWTH_CHOICES = [3, 5]
QUARTERLY_GROWTH_CHOICES = [3, 5]
VOLUME_RATIO_CHOICES = [5, 10]
VOLUME_SURGE_MIN_DAY_CHOICES = [3, 5]

FIXED_ANNUAL_YEARS = 3
FIXED_QUARTER_COUNT = 4
FIXED_DAILY_MA_TOLERANCE_PCT = 1
FIXED_WEEKLY_MA_TOLERANCE_PCT = 2
DEFAULT_START_DATE = "2022-01-01"


@dataclass(frozen=True)
class BacktestParameterCombination:
    annual_growth_pct: int
    quarterly_growth_pct: int
    volume_ratio_threshold: int
    volume_surge_min_days: int

    @property
    def parameter_set_name(self) -> str:
        return (
            f"grid_ag{self.annual_growth_pct}"
            f"_qg{self.quarterly_growth_pct}"
            f"_vr{self.volume_ratio_threshold}"
            f"_vd{self.volume_surge_min_days}"
        )

    @property
    def result_table_name(self) -> str:
        return (
            f"backtest_result_ag{self.annual_growth_pct}"
            f"_qg{self.quarterly_growth_pct}"
            f"_vr{self.volume_ratio_threshold}"
            f"_vd{self.volume_surge_min_days}"
        )


def parameter_grid() -> list[BacktestParameterCombination]:
    return [
        BacktestParameterCombination(
            annual_growth_pct=annual_growth_pct,
            quarterly_growth_pct=quarterly_growth_pct,
            volume_ratio_threshold=volume_ratio_threshold,
            volume_surge_min_days=volume_surge_min_days,
        )
        for annual_growth_pct in ANNUAL_GROWTH_CHOICES
        for quarterly_growth_pct in QUARTERLY_GROWTH_CHOICES
        for volume_ratio_threshold in VOLUME_RATIO_CHOICES
        for volume_surge_min_days in VOLUME_SURGE_MIN_DAY_CHOICES
    ]


def grid_parameter_names() -> list[str]:
    return [combo.parameter_set_name for combo in parameter_grid()]


def result_table_names() -> list[str]:
    return [combo.result_table_name for combo in parameter_grid()]


def result_table_for_parameter_set(parameter_set_name: str) -> str:
    for combo in parameter_grid():
        if combo.parameter_set_name == parameter_set_name:
            return combo.result_table_name
    raise ValueError(f"Unknown grid parameter set: {parameter_set_name}")

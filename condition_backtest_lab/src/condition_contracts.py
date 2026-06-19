from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionContract:
    condition: str
    label: str
    data_grain: str
    timing: str
    rule: str


CONDITION_CONTRACTS = {
    "A": ConditionContract(
        "A",
        "Annual growth",
        "annual fundamental period",
        "Latest required valid annual periods with datadate on/before signal date.",
        "Revenue and operating-income growth each meet the selected threshold.",
    ),
    "B": ConditionContract(
        "B",
        "Quarterly growth",
        "quarterly fundamental period",
        "Latest required valid quarterly periods with datadate on/before signal date.",
        "Revenue and operating-income growth each meet the selected threshold.",
    ),
    "C": ConditionContract(
        "C",
        "Daily volume ratio",
        "daily security row",
        "Evaluated on the daily signal date.",
        "Volume ratio meets the selected threshold.",
    ),
    "D": ConditionContract(
        "D",
        "Recent volume-surge frequency",
        "rolling daily security history",
        "Evaluated through the daily signal date.",
        "Selected minimum surge-day count is met over the trailing three months.",
    ),
    "E": ConditionContract(
        "E",
        "Daily moving-average setup",
        "daily security row",
        "Evaluated on the daily signal date.",
        "All daily moving-average pairs are within the selected tolerance.",
    ),
    "F": ConditionContract(
        "F",
        "Daily crossover confirmation",
        "immediately following official-session security row",
        "Evaluated only on the official market session immediately following E.",
        "MA20 is at/below MA50 on E and above MA50 on the confirmation row.",
    ),
    "G": ConditionContract(
        "G",
        "Weekly moving-average setup",
        "completed official trading week",
        "Evaluated only on a completed official trading week.",
        "All weekly moving-average pairs are within the selected tolerance.",
    ),
    "H": ConditionContract(
        "H",
        "Weekly crossover confirmation",
        "following completed official trading week",
        "Evaluated on the completed official trading week immediately after G.",
        "WMA10 is at/below WMA30 on G and above WMA30 on the following week.",
    ),
}

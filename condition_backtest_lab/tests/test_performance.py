from __future__ import annotations

import unittest

import pandas as pd

from condition_backtest_lab.src.performance import GROUPS, apply_cooldown


class PerformanceCooldownTest(unittest.TestCase):
    def test_performance_uses_actionable_confirmation_dates(self) -> None:
        self.assertEqual(GROUPS["ef"][0], "f_confirmation_date")
        self.assertEqual(GROUPS["gh"][0], "h_confirmation_date")
        self.assertEqual(GROUPS["cdef"][0], "confirmation_date")
        self.assertEqual(GROUPS["cdgh"][0], "confirmation_date")

    def test_cooldown_is_measured_from_last_retained_event(self) -> None:
        events = pd.DataFrame(
            [
                ["cd", 1, "2024-01-01", "1", "01", "AAA"],
                ["cd", 1, "2024-06-01", "1", "01", "AAA"],
                ["cd", 1, "2024-07-01", "1", "01", "AAA"],
                ["cd", 1, "2024-12-30", "1", "01", "AAA"],
            ],
            columns=["group_name", "parameter_id", "selection_date", "gvkey", "iid", "ticker"],
        )
        events["selection_date"] = pd.to_datetime(events["selection_date"])

        retained = apply_cooldown(events)

        self.assertEqual(
            retained["selection_date"].dt.strftime("%Y-%m-%d").tolist(),
            ["2024-01-01", "2024-07-01", "2024-12-30"],
        )

    def test_parameter_combinations_are_independent(self) -> None:
        events = pd.DataFrame(
            [
                ["cd", 1, "2024-01-01", "1", "01", "AAA"],
                ["cd", 2, "2024-01-01", "1", "01", "AAA"],
            ],
            columns=["group_name", "parameter_id", "selection_date", "gvkey", "iid", "ticker"],
        )
        events["selection_date"] = pd.to_datetime(events["selection_date"])

        self.assertEqual(len(apply_cooldown(events)), 2)


if __name__ == "__main__":
    unittest.main()

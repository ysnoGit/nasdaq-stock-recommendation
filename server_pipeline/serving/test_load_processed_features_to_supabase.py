from __future__ import annotations

from datetime import date
import unittest

from server_pipeline.serving.load_processed_features_to_supabase import (
    DEFAULT_SERVING_HISTORY_START_DATE,
    daily_history_window,
    rolling_daily_history_start,
)
from server_pipeline.utils.trading_calendar import (
    official_week_end_trading_date,
    week_start_for_date,
)


class ServingHistoryWindowTest(unittest.TestCase):
    def test_daily_history_window_is_inclusive(self):
        paths = [
            {"key": value, "date": value}
            for value in ("2024-05-31", "2024-06-03", "2024-06-04")
        ]

        selected = daily_history_window(paths, DEFAULT_SERVING_HISTORY_START_DATE)

        self.assertEqual(
            [item["date"] for item in selected],
            ["2024-06-03", "2024-06-04"],
        )

    def test_default_boundary_maps_to_requested_first_week(self):
        week_start = week_start_for_date(DEFAULT_SERVING_HISTORY_START_DATE)

        self.assertEqual(week_start, date(2024, 6, 3))
        self.assertEqual(official_week_end_trading_date(week_start), date(2024, 6, 7))

    def test_daily_history_supports_fifteen_recent_inspection_sessions(self):
        history_start, inspection_start = rolling_daily_history_start(
            date(2026, 6, 18),
            lookback_months=3,
            inspection_trading_days=15,
        )

        self.assertEqual(inspection_start, date(2026, 5, 29))
        self.assertEqual(history_start, date(2026, 2, 28))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import date
import unittest

from server_pipeline.daily.build_daily_market_metrics_s3 import (
    choose_input_files as choose_daily_input_files,
)
from server_pipeline.daily.build_weekly_market_metrics_s3 import (
    choose_input_files as choose_weekly_input_files,
)


class HistoricalRebuildWindowTest(unittest.TestCase):
    def setUp(self):
        self.yearly = [
            {"year": year, "path": f"s3://bucket/raw/year={year}.parquet"}
            for year in (2023, 2024, 2025)
        ]
        self.daily = [
            {
                "date": date(2026, 6, 18),
                "path": "s3://bucket/raw/date=2026-06-18.parquet",
            }
        ]

    def test_daily_start_date_expands_raw_warmup_window(self):
        paths, target_dates, warmup_start, latest = choose_daily_input_files(
            self.yearly,
            self.daily,
            target_days=5,
            warmup_calendar_days=250,
            start_date=date(2024, 6, 3),
        )

        self.assertEqual(warmup_start, date(2023, 9, 27))
        self.assertEqual(target_dates[0], date(2024, 6, 3))
        self.assertEqual(latest, date(2026, 6, 18))
        self.assertIn("s3://bucket/raw/year=2023.parquet", paths)
        self.assertIn("s3://bucket/raw/year=2024.parquet", paths)

    def test_weekly_start_date_expands_raw_warmup_window(self):
        paths, warmup_start, latest = choose_weekly_input_files(
            self.yearly,
            self.daily,
            target_weeks=8,
            warmup_calendar_days=500,
            start_week_date=date(2024, 6, 3),
        )

        self.assertEqual(warmup_start, date(2023, 1, 20))
        self.assertEqual(latest, date(2026, 6, 18))
        self.assertIn("s3://bucket/raw/year=2023.parquet", paths)
        self.assertIn("s3://bucket/raw/year=2024.parquet", paths)


if __name__ == "__main__":
    unittest.main()

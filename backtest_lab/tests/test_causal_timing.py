from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from backtest_lab.src import price_outcome
from backtest_lab.src.price_outcome import calculate_price_outcomes
from backtest_lab.src.screening_logic import evaluate_parameter


class CausalTimingTest(unittest.TestCase):
    def test_confirmation_dates_and_entry_prices_are_causal(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE daily (
                snapshot_date DATE, gvkey VARCHAR, iid VARCHAR, ticker VARCHAR,
                company_name VARCHAR, close_price DOUBLE, adjusted_close_price DOUBLE,
                volume_ratio DOUBLE, ma20 DOUBLE, ma50 DOUBLE, ma100 DOUBLE,
                future_daily_confirmation_date DATE,
                future_daily_close_price DOUBLE,
                future_daily_adjusted_close_price DOUBLE,
                future_daily_ma20 DOUBLE, future_daily_ma50 DOUBLE,
                future_daily_ma100 DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    date(2026, 5, 26), "1", "01", "TEST", "Test Company",
                    100, 100, 3, 100, 100, 100,
                    date(2026, 5, 27), 105, 105, 100, 100, 100,
                ),
                (
                    date(2026, 5, 27), "1", "01", "TEST", "Test Company",
                    105, 105, 1, 100, 100, 100,
                    date(2026, 5, 28), 106, 106, 100, 100, 100,
                ),
                (
                    date(2026, 6, 5), "1", "01", "TEST", "Test Company",
                    120, 120, 1, 100, 100, 100,
                    date(2026, 6, 8), 121, 121, 100, 100, 100,
                ),
                (
                    date(2026, 6, 8), "1", "01", "TEST", "Test Company",
                    121, 121, 1, 100, 100, 100,
                    None, None, None, None, None, None,
                ),
            ],
        )
        con.execute(
            """
            CREATE TABLE weekly (
                week_end_date DATE, gvkey VARCHAR, iid VARCHAR,
                weekly_close_price DOUBLE, weekly_ma5 DOUBLE, weekly_ma10 DOUBLE,
                weekly_ma30 DOUBLE, future_weekly_confirmation_date DATE,
                future_weekly_close_price DOUBLE, future_weekly_ma5 DOUBLE,
                future_weekly_ma10 DOUBLE, future_weekly_ma30 DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO weekly VALUES
            ('2026-05-29', '1', '01', 108, 100, 100, 100,
             '2026-06-05', 120, 100, 100, 100)
            """
        )
        con.execute(
            """
            CREATE TABLE annual (
                gvkey VARCHAR, datadate DATE, annual_revenue_growth DOUBLE,
                annual_operating_income_growth DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO annual VALUES
            ('1', '2025-12-31', 0.10, 0.10),
            ('1', '2024-12-31', 0.10, 0.10)
            """
        )
        con.execute(
            """
            CREATE TABLE quarterly (
                gvkey VARCHAR, datadate DATE, quarterly_revenue_growth DOUBLE,
                quarterly_operating_income_growth DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO quarterly VALUES
            ('1', '2026-03-31', 0.10, 0.10),
            ('1', '2025-12-31', 0.10, 0.10)
            """
        )

        parameter = {
            "parameter_set_id": 2,
            "start_date": date(2026, 5, 26),
            "end_date": date(2026, 6, 8),
            "annual_growth_pct": 2,
            "quarterly_growth_pct": 2,
            "annual_years": 2,
            "quarter_count": 2,
            "volume_ratio_threshold": 2,
            "volume_surge_min_days": 1,
            "daily_ma_tolerance_pct": 1,
            "weekly_ma_tolerance_pct": 2,
        }

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            selection_path = tmp_path / "selections.parquet"
            daily_path = tmp_path / "daily.parquet"
            selections = evaluate_parameter(con, parameter)
            selections.write_parquet(str(selection_path))
            con.sql("SELECT * FROM daily").write_parquet(str(daily_path))

            rows = {
                row[0]: row
                for row in con.execute(
                    f"""
                    SELECT screen_type, signal_date, f_confirmation_date,
                           g_confirmation_date, h_confirmation_date, selected_date,
                           selected_price
                    FROM read_parquet('{selection_path}')
                    """
                ).fetchall()
            }
            self.assertEqual(
                rows["A_F"],
                (
                    "A_F", date(2026, 5, 26), date(2026, 5, 27),
                    None, None, date(2026, 5, 27), 105.0,
                ),
            )
            self.assertEqual(
                rows["A_H"],
                (
                    "A_H", date(2026, 5, 26), date(2026, 5, 27),
                    date(2026, 5, 29), date(2026, 6, 5),
                    date(2026, 6, 5), 120.0,
                ),
            )

            original_path = price_outcome.DAILY_FEATURE_PATH
            price_outcome.DAILY_FEATURE_PATH = daily_path
            try:
                outcomes = calculate_price_outcomes(con, selection_path, "test").df()
            finally:
                price_outcome.DAILY_FEATURE_PATH = original_path

            returns = dict(zip(outcomes["screen_type"], outcomes["return_pct"]))
            self.assertAlmostEqual(returns["A_F"], (121 / 105 - 1) * 100)
            self.assertAlmostEqual(returns["A_H"], (121 / 120 - 1) * 100)
            drawdowns = dict(zip(outcomes["screen_type"], outcomes["max_drawdown_pct"]))
            self.assertAlmostEqual(drawdowns["A_F"], 0.0)
            self.assertAlmostEqual(drawdowns["A_H"], 0.0)
            self.assertTrue(outcomes["return_6m_pct"].isna().all())
            self.assertTrue(outcomes["return_1y_pct"].isna().all())
            self.assertTrue(outcomes["return_2y_pct"].isna().all())

    def test_fixed_horizon_returns_use_first_price_on_or_after_anniversary(self):
        con = duckdb.connect()
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            selection_path = tmp_path / "selections.parquet"
            daily_path = tmp_path / "daily.parquet"
            con.execute(
                """
                CREATE TABLE selections AS SELECT
                    1::BIGINT AS parameter_set_id, 'A_F' AS screen_type,
                    DATE '2024-01-01' AS signal_date,
                    DATE '2024-01-02' AS f_confirmation_date,
                    NULL::DATE AS g_confirmation_date,
                    NULL::DATE AS h_confirmation_date,
                    DATE '2024-01-02' AS selected_date,
                    '1' AS gvkey, '01' AS iid, 'TEST' AS ticker,
                    'Test Company' AS company_name,
                    100.0 AS selected_price, 100.0 AS selected_adjusted_price,
                    TRUE AS flag_a, TRUE AS flag_b, TRUE AS flag_c,
                    TRUE AS flag_d, TRUE AS flag_e, TRUE AS flag_f,
                    NULL::BOOLEAN AS flag_g, NULL::BOOLEAN AS flag_h
                """
            )
            con.execute(
                """
                CREATE TABLE horizon_daily (
                    snapshot_date DATE, gvkey VARCHAR, iid VARCHAR,
                    close_price DOUBLE, adjusted_close_price DOUBLE
                )
                """
            )
            con.execute(
                """
                INSERT INTO horizon_daily VALUES
                    ('2024-01-02', '1', '01', 100, 100),
                    ('2024-07-01', '1', '01', 105, 105),
                    ('2024-07-02', '1', '01', 110, 110),
                    ('2025-01-02', '1', '01', 120, 120),
                    ('2026-01-02', '1', '01', 150, 150)
                """
            )
            con.sql("SELECT * FROM selections").write_parquet(str(selection_path))
            con.sql("SELECT * FROM horizon_daily").write_parquet(str(daily_path))

            original_path = price_outcome.DAILY_FEATURE_PATH
            price_outcome.DAILY_FEATURE_PATH = daily_path
            try:
                outcome = calculate_price_outcomes(con, selection_path, "test").df().iloc[0]
            finally:
                price_outcome.DAILY_FEATURE_PATH = original_path

            self.assertEqual(outcome["return_6m_date"].date(), date(2024, 7, 2))
            self.assertEqual(outcome["return_1y_date"].date(), date(2025, 1, 2))
            self.assertEqual(outcome["return_2y_date"].date(), date(2026, 1, 2))
            self.assertAlmostEqual(outcome["return_6m_pct"], 10.0)
            self.assertAlmostEqual(outcome["return_1y_pct"], 20.0)
            self.assertAlmostEqual(outcome["return_2y_pct"], 50.0)

    def test_g_confirmation_cannot_precede_f_confirmation(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE daily (
                snapshot_date DATE, gvkey VARCHAR, iid VARCHAR, ticker VARCHAR,
                company_name VARCHAR, close_price DOUBLE, adjusted_close_price DOUBLE,
                volume_ratio DOUBLE, ma20 DOUBLE, ma50 DOUBLE, ma100 DOUBLE,
                future_daily_confirmation_date DATE,
                future_daily_close_price DOUBLE,
                future_daily_adjusted_close_price DOUBLE,
                future_daily_ma20 DOUBLE, future_daily_ma50 DOUBLE,
                future_daily_ma100 DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily VALUES
            ('2026-05-29', '1', '01', 'TEST', 'Test Company', 100, 100, 3,
             100, 100, 100, '2026-06-01', 101, 101, 100, 100, 100)
            """
        )
        con.execute(
            """
            CREATE TABLE weekly (
                week_end_date DATE, gvkey VARCHAR, iid VARCHAR,
                weekly_close_price DOUBLE, weekly_ma5 DOUBLE, weekly_ma10 DOUBLE,
                weekly_ma30 DOUBLE, future_weekly_confirmation_date DATE,
                future_weekly_close_price DOUBLE, future_weekly_ma5 DOUBLE,
                future_weekly_ma10 DOUBLE, future_weekly_ma30 DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO weekly VALUES
            ('2026-05-29', '1', '01', 100, 100, 100, 100,
             '2026-06-05', 110, 100, 100, 100),
            ('2026-06-05', '1', '01', 110, 100, 100, 100,
             '2026-06-12', 120, 100, 100, 100)
            """
        )
        con.execute(
            """
            CREATE TABLE annual (
                gvkey VARCHAR, datadate DATE, annual_revenue_growth DOUBLE,
                annual_operating_income_growth DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO annual VALUES
            ('1', '2025-12-31', 0.10, 0.10),
            ('1', '2024-12-31', 0.10, 0.10)
            """
        )
        con.execute(
            """
            CREATE TABLE quarterly (
                gvkey VARCHAR, datadate DATE, quarterly_revenue_growth DOUBLE,
                quarterly_operating_income_growth DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO quarterly VALUES
            ('1', '2026-03-31', 0.10, 0.10),
            ('1', '2025-12-31', 0.10, 0.10)
            """
        )
        parameter = {
            "parameter_set_id": 2, "start_date": date(2026, 5, 29),
            "end_date": date(2026, 6, 12), "annual_growth_pct": 2,
            "quarterly_growth_pct": 2, "annual_years": 2, "quarter_count": 2,
            "volume_ratio_threshold": 2, "volume_surge_min_days": 1,
            "daily_ma_tolerance_pct": 1, "weekly_ma_tolerance_pct": 2,
        }
        rows = evaluate_parameter(con, parameter).filter("screen_type = 'A_H'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], date(2026, 6, 1))
        self.assertEqual(rows[0][4], date(2026, 6, 5))
        self.assertEqual(rows[0][5], date(2026, 6, 12))


if __name__ == "__main__":
    unittest.main()

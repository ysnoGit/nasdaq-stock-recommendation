from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from server_pipeline.fundamentals.build_fundamental_growth_history_s3 import (
    build_annual_growth_history,
    build_quarterly_growth_history,
)


class AnnualGrowthHistoryTest(unittest.TestCase):
    def test_nonconsecutive_year_does_not_produce_yoy_growth(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, currency VARCHAR, exchange_code INTEGER,
                sale DOUBLE, revt DOUBLE, oiadp DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('1', '2019-12-31', 2019, 'TEST', 'Test Co', 'USD', 14, 100, NULL, 10),
                ('1', '2020-12-31', 2020, 'TEST', 'Test Co', 'USD', 14, 120, NULL, 12),
                ('1', '2022-12-31', 2022, 'TEST', 'Test Co', 'USD', 14, 180, NULL, 18);
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "annual.parquet"
            con.sql("SELECT * FROM annual_source").write_parquet(str(path))
            result = build_annual_growth_history(con, str(path), "2026-06-14T00:00:00")

        row_2020 = result[result["fyear"] == 2020].iloc[0]
        row_2022 = result[result["fyear"] == 2022].iloc[0]
        self.assertAlmostEqual(row_2020["annual_revenue_growth_yoy"], 0.20)
        self.assertEqual(row_2022["prev_annual_fyear"], 2020)
        self.assertTrue(row_2022["annual_revenue_growth_yoy"] != row_2022["annual_revenue_growth_yoy"])
        self.assertFalse(row_2022["has_valid_annual_growth_pair"])

    def test_annual_growth_handles_negative_and_zero_previous_values(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, currency VARCHAR, exchange_code INTEGER,
                sale DOUBLE, revt DOUBLE, oiadp DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('improve', '2019-12-31', 2019, 'A', 'A', 'USD', 14, -100, NULL, -100),
                ('improve', '2020-12-31', 2020, 'A', 'A', 'USD', 14, -50, NULL, -50),
                ('worsen', '2019-12-31', 2019, 'B', 'B', 'USD', 14, -100, NULL, -100),
                ('worsen', '2020-12-31', 2020, 'B', 'B', 'USD', 14, -150, NULL, -150),
                ('turnaround', '2019-12-31', 2019, 'C', 'C', 'USD', 14, -100, NULL, -100),
                ('turnaround', '2020-12-31', 2020, 'C', 'C', 'USD', 14, 50, NULL, 50),
                ('zero', '2019-12-31', 2019, 'D', 'D', 'USD', 14, 0, NULL, 0),
                ('zero', '2020-12-31', 2020, 'D', 'D', 'USD', 14, 50, NULL, 50),
                ('loss', '2019-12-31', 2019, 'E', 'E', 'USD', 14, 100, NULL, 100),
                ('loss', '2020-12-31', 2020, 'E', 'E', 'USD', 14, -50, NULL, -50),
                ('break_even', '2019-12-31', 2019, 'F', 'F', 'USD', 14, -100, NULL, -100),
                ('break_even', '2020-12-31', 2020, 'F', 'F', 'USD', 14, 0, NULL, 0);
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "annual.parquet"
            con.sql("SELECT * FROM annual_source").write_parquet(str(path))
            result = build_annual_growth_history(con, str(path), "2026-06-14T00:00:00")

        current = result[result["fyear"] == 2020].set_index("gvkey")
        self.assertAlmostEqual(current.loc["improve", "annual_revenue_growth_yoy"], 0.50)
        self.assertAlmostEqual(current.loc["worsen", "annual_revenue_growth_yoy"], -0.50)
        self.assertAlmostEqual(current.loc["turnaround", "annual_revenue_growth_yoy"], 1.50)
        self.assertAlmostEqual(current.loc["loss", "annual_revenue_growth_yoy"], -1.50)
        self.assertAlmostEqual(current.loc["break_even", "annual_revenue_growth_yoy"], 1.00)
        self.assertAlmostEqual(current.loc["improve", "annual_operating_income_growth_yoy"], 0.50)
        self.assertAlmostEqual(current.loc["worsen", "annual_operating_income_growth_yoy"], -0.50)
        self.assertAlmostEqual(current.loc["turnaround", "annual_operating_income_growth_yoy"], 1.50)
        self.assertAlmostEqual(current.loc["loss", "annual_operating_income_growth_yoy"], -1.50)
        self.assertAlmostEqual(current.loc["break_even", "annual_operating_income_growth_yoy"], 1.00)
        self.assertTrue(current.loc["zero", "annual_revenue_growth_yoy"] != current.loc["zero", "annual_revenue_growth_yoy"])
        self.assertFalse(current.loc["zero", "has_valid_annual_growth_pair"])


class QuarterlyGrowthHistoryTest(unittest.TestCase):
    def test_quarterly_growth_handles_negative_and_zero_previous_values(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE quarterly_source (
                gvkey VARCHAR, datadate DATE, fyearq INTEGER, fqtr INTEGER,
                ticker VARCHAR, company_name VARCHAR, currency VARCHAR,
                exchange_code INTEGER, saleq DOUBLE, revtq DOUBLE, oiadpq DOUBLE
            );
            INSERT INTO quarterly_source VALUES
                ('improve', '2019-03-31', 2019, 1, 'A', 'A', 'USD', 14, -100, NULL, -100),
                ('improve', '2020-03-31', 2020, 1, 'A', 'A', 'USD', 14, -50, NULL, -50),
                ('worsen', '2019-03-31', 2019, 1, 'B', 'B', 'USD', 14, -100, NULL, -100),
                ('worsen', '2020-03-31', 2020, 1, 'B', 'B', 'USD', 14, -150, NULL, -150),
                ('turnaround', '2019-03-31', 2019, 1, 'C', 'C', 'USD', 14, -100, NULL, -100),
                ('turnaround', '2020-03-31', 2020, 1, 'C', 'C', 'USD', 14, 50, NULL, 50),
                ('zero', '2019-03-31', 2019, 1, 'D', 'D', 'USD', 14, 0, NULL, 0),
                ('zero', '2020-03-31', 2020, 1, 'D', 'D', 'USD', 14, 50, NULL, 50),
                ('loss', '2019-03-31', 2019, 1, 'E', 'E', 'USD', 14, 100, NULL, 100),
                ('loss', '2020-03-31', 2020, 1, 'E', 'E', 'USD', 14, -50, NULL, -50),
                ('break_even', '2019-03-31', 2019, 1, 'F', 'F', 'USD', 14, -100, NULL, -100),
                ('break_even', '2020-03-31', 2020, 1, 'F', 'F', 'USD', 14, 0, NULL, 0);
            """
        )
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "quarterly.parquet"
            con.sql("SELECT * FROM quarterly_source").write_parquet(str(path))
            result = build_quarterly_growth_history(con, str(path), "2026-06-14T00:00:00")

        current = result[result["fyearq"] == 2020].set_index("gvkey")
        self.assertAlmostEqual(current.loc["improve", "quarterly_revenue_growth_yoy"], 0.50)
        self.assertAlmostEqual(current.loc["worsen", "quarterly_revenue_growth_yoy"], -0.50)
        self.assertAlmostEqual(current.loc["turnaround", "quarterly_revenue_growth_yoy"], 1.50)
        self.assertAlmostEqual(current.loc["loss", "quarterly_revenue_growth_yoy"], -1.50)
        self.assertAlmostEqual(current.loc["break_even", "quarterly_revenue_growth_yoy"], 1.00)
        self.assertAlmostEqual(current.loc["improve", "quarterly_operating_income_growth_yoy"], 0.50)
        self.assertAlmostEqual(current.loc["worsen", "quarterly_operating_income_growth_yoy"], -0.50)
        self.assertAlmostEqual(current.loc["turnaround", "quarterly_operating_income_growth_yoy"], 1.50)
        self.assertAlmostEqual(current.loc["loss", "quarterly_operating_income_growth_yoy"], -1.50)
        self.assertAlmostEqual(current.loc["break_even", "quarterly_operating_income_growth_yoy"], 1.00)
        self.assertTrue(current.loc["zero", "quarterly_revenue_growth_yoy"] != current.loc["zero", "quarterly_revenue_growth_yoy"])
        self.assertFalse(current.loc["zero", "has_valid_quarterly_growth_pair"])


if __name__ == "__main__":
    unittest.main()

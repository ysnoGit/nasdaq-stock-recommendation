from datetime import date
import unittest

import duckdb

from condition_backtest_lab.src.ab_coverage import (
    build_ab_parameter_grid,
    create_ab_coverage_tables,
)


class ABCoverageTest(unittest.TestCase):
    def test_parameter_grid_has_300_unique_combinations(self):
        grid = build_ab_parameter_grid()
        self.assertEqual(len(grid), 300)
        self.assertEqual(grid["parameter_name"].nunique(), 300)

    def test_zero_selection_quarter_is_retained_when_company_is_eligible(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, annual_revenue_growth_yoy DOUBLE,
                annual_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('1', '2017-12-31', 2017, 'TEST', 'Test Co', NULL, NULL),
                ('1', '2018-12-31', 2018, 'TEST', 'Test Co', 0.01, 0.01),
                ('1', '2019-12-31', 2019, 'TEST', 'Test Co', 0.01, 0.01);

            CREATE TABLE quarterly_source (
                gvkey VARCHAR, datadate DATE, fyearq INTEGER, fqtr INTEGER,
                ticker VARCHAR, company_name VARCHAR,
                quarterly_revenue_growth_yoy DOUBLE,
                quarterly_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO quarterly_source VALUES
                ('1', '2019-09-30', 2019, 3, 'TEST', 'Test Co', 0.01, 0.01),
                ('1', '2019-12-31', 2019, 4, 'TEST', 'Test Co', 0.01, 0.01);
            """
        )
        create_ab_coverage_tables(
            con,
            date(2020, 1, 1),
            date(2020, 3, 31),
            annual_path="annual_source",
            quarterly_path="quarterly_source",
        )
        result = con.execute(
            """
            SELECT eligible_company_count, selected_company_count
            FROM ab_quarterly_coverage
            WHERE annual_growth_pct = 3 AND annual_years = 2
              AND quarterly_growth_pct = 3 AND quarter_count = 2
            """
        ).fetchone()
        self.assertEqual(result, (1, 0))

    def test_quarter_without_any_eligible_company_is_excluded(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, annual_revenue_growth_yoy DOUBLE,
                annual_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('1', '2019-12-31', 2019, 'TEST', 'Test Co', 0.10, 0.10);

            CREATE TABLE quarterly_source (
                gvkey VARCHAR, datadate DATE, fyearq INTEGER, fqtr INTEGER,
                ticker VARCHAR, company_name VARCHAR,
                quarterly_revenue_growth_yoy DOUBLE,
                quarterly_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO quarterly_source VALUES
                ('1', '2019-12-31', 2019, 4, 'TEST', 'Test Co', 0.10, 0.10);
            """
        )
        create_ab_coverage_tables(
            con,
            date(2020, 1, 1),
            date(2020, 3, 31),
            annual_path="annual_source",
            quarterly_path="quarterly_source",
        )
        count = con.execute("SELECT COUNT(*) FROM ab_quarterly_coverage").fetchone()[0]
        self.assertEqual(count, 0)

    def test_nonconsecutive_latest_annual_periods_are_not_eligible(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, annual_revenue_growth_yoy DOUBLE,
                annual_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('1', '2018-12-31', 2018, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2020-12-31', 2020, 'TEST', 'Test Co', 0.10, 0.10);

            CREATE TABLE quarterly_source (
                gvkey VARCHAR, datadate DATE, fyearq INTEGER, fqtr INTEGER,
                ticker VARCHAR, company_name VARCHAR,
                quarterly_revenue_growth_yoy DOUBLE,
                quarterly_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO quarterly_source VALUES
                ('1', '2020-09-30', 2020, 3, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2020-12-31', 2020, 4, 'TEST', 'Test Co', 0.10, 0.10);
            """
        )
        create_ab_coverage_tables(
            con,
            date(2021, 1, 1),
            date(2021, 3, 31),
            annual_path="annual_source",
            quarterly_path="quarterly_source",
        )
        count = con.execute("SELECT COUNT(*) FROM ab_quarterly_coverage").fetchone()[0]
        self.assertEqual(count, 0)

    def test_nonconsecutive_latest_quarterly_periods_are_not_eligible(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, annual_revenue_growth_yoy DOUBLE,
                annual_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('1', '2019-12-31', 2019, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2020-12-31', 2020, 'TEST', 'Test Co', 0.10, 0.10);

            CREATE TABLE quarterly_source (
                gvkey VARCHAR, datadate DATE, fyearq INTEGER, fqtr INTEGER,
                ticker VARCHAR, company_name VARCHAR,
                quarterly_revenue_growth_yoy DOUBLE,
                quarterly_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO quarterly_source VALUES
                ('1', '2020-06-30', 2020, 2, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2020-12-31', 2020, 4, 'TEST', 'Test Co', 0.10, 0.10);
            """
        )
        create_ab_coverage_tables(
            con,
            date(2021, 1, 1),
            date(2021, 3, 31),
            annual_path="annual_source",
            quarterly_path="quarterly_source",
        )
        count = con.execute("SELECT COUNT(*) FROM ab_quarterly_coverage").fetchone()[0]
        self.assertEqual(count, 0)

    def test_missing_latest_growth_pair_is_not_skipped(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE annual_source (
                gvkey VARCHAR, datadate DATE, fyear INTEGER, ticker VARCHAR,
                company_name VARCHAR, annual_revenue_growth_yoy DOUBLE,
                annual_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO annual_source VALUES
                ('1', '2018-12-31', 2018, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2019-12-31', 2019, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2020-12-31', 2020, 'TEST', 'Test Co', NULL, NULL);

            CREATE TABLE quarterly_source (
                gvkey VARCHAR, datadate DATE, fyearq INTEGER, fqtr INTEGER,
                ticker VARCHAR, company_name VARCHAR,
                quarterly_revenue_growth_yoy DOUBLE,
                quarterly_operating_income_growth_yoy DOUBLE
            );
            INSERT INTO quarterly_source VALUES
                ('1', '2020-09-30', 2020, 3, 'TEST', 'Test Co', 0.10, 0.10),
                ('1', '2020-12-31', 2020, 4, 'TEST', 'Test Co', 0.10, 0.10);
            """
        )
        create_ab_coverage_tables(
            con,
            date(2021, 1, 1),
            date(2021, 3, 31),
            annual_path="annual_source",
            quarterly_path="quarterly_source",
        )
        count = con.execute("SELECT COUNT(*) FROM ab_quarterly_coverage").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

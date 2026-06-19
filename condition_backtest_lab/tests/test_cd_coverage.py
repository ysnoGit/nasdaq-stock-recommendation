from datetime import date
import unittest

import duckdb

from condition_backtest_lab.src.cd_coverage import (
    build_cd_parameter_grid,
    create_cd_coverage_tables,
)


class CDCoverageTest(unittest.TestCase):
    def create_source(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE daily_source (
                snapshot_date DATE,
                gvkey VARCHAR,
                iid VARCHAR,
                ticker VARCHAR,
                company_name VARCHAR,
                volume DOUBLE,
                volume_ma30 DOUBLE,
                volume_ratio DOUBLE
            );
            INSERT INTO daily_source
            SELECT
                CAST(day AS DATE),
                '1',
                iid,
                'ONE',
                'One Co',
                CASE WHEN CAST(day AS DATE) IN (
                    DATE '2020-02-03', DATE '2020-03-02', DATE '2020-04-01'
                ) THEN 100 ELSE 10 END,
                10,
                CASE WHEN CAST(day AS DATE) IN (
                    DATE '2020-02-03', DATE '2020-03-02', DATE '2020-04-01'
                ) THEN 10 ELSE 1 END
            FROM generate_series(
                DATE '2020-01-01', DATE '2020-04-02', INTERVAL 1 DAY
            ) dates(day)
            CROSS JOIN (VALUES ('01'), ('02')) issues(iid);
            """
        )
        return con

    def test_parameter_grid_has_18_unique_combinations(self):
        grid = build_cd_parameter_grid()
        self.assertEqual(len(grid), 18)
        self.assertEqual(grid["parameter_name"].nunique(), 18)

    def test_earliest_date_requires_complete_three_month_history(self):
        con = self.create_source()
        create_cd_coverage_tables(con, daily_path="daily_source")
        first_date = con.execute(
            "SELECT MIN(evaluation_date) FROM cd_daily_coverage"
        ).fetchone()[0]
        self.assertEqual(first_date, date(2020, 4, 1))

    def test_current_date_is_included_in_surge_count(self):
        con = self.create_source()
        create_cd_coverage_tables(con, daily_path="daily_source")
        result = con.execute(
            """
            SELECT surge_day_count
            FROM cd_selections
            WHERE parameter_name = 'cd_vr10_vd3'
              AND evaluation_date = DATE '2020-04-01'
              AND iid = '01'
            """
        ).fetchone()
        self.assertEqual(result, (3,))

    def test_company_is_counted_once_when_multiple_issues_pass(self):
        con = self.create_source()
        create_cd_coverage_tables(con, daily_path="daily_source")
        result = con.execute(
            """
            SELECT eligible_company_count, eligible_security_count, selected_company_count
            FROM cd_daily_coverage
            WHERE parameter_name = 'cd_vr10_vd3'
              AND evaluation_date = DATE '2020-04-01'
            """
        ).fetchone()
        self.assertEqual(result, (1, 2, 1))

    def test_genuine_zero_selection_date_is_retained(self):
        con = self.create_source()
        create_cd_coverage_tables(con, daily_path="daily_source")
        result = con.execute(
            """
            SELECT eligible_company_count, selected_company_count
            FROM cd_daily_coverage
            WHERE parameter_name = 'cd_vr5_vd3'
              AND evaluation_date = DATE '2020-04-02'
            """
        ).fetchone()
        self.assertEqual(result, (1, 0))

    def test_non_null_partial_window_ratio_is_not_eligible(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE daily_source (
                snapshot_date DATE,
                gvkey VARCHAR,
                iid VARCHAR,
                ticker VARCHAR,
                company_name VARCHAR,
                volume DOUBLE,
                volume_ma30 DOUBLE,
                volume_ratio DOUBLE
            );
            INSERT INTO daily_source
            SELECT
                CAST(day AS DATE), '1', '01', 'ONE', 'One Co', 100, 10, 10
            FROM generate_series(
                DATE '2020-01-01', DATE '2020-04-01', INTERVAL 7 DAY
            ) dates(day);
            """
        )
        create_cd_coverage_tables(con, daily_path="daily_source")
        count = con.execute("SELECT COUNT(*) FROM cd_daily_coverage").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

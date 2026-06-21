from datetime import date
import unittest

import duckdb

from condition_backtest_lab.src.gh_coverage import (
    build_gh_parameter_grid,
    create_gh_coverage_tables,
)


class GHCoverageTest(unittest.TestCase):
    def create_source(self, h_date: str = "2024-06-07") -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute(
            f"""
            CREATE TABLE weekly_source (
                week_end_date DATE,
                gvkey VARCHAR,
                iid VARCHAR,
                weekly_ma5 DOUBLE,
                weekly_ma10 DOUBLE,
                weekly_ma30 DOUBLE,
                future_weekly_confirmation_date DATE,
                future_weekly_close_price DOUBLE,
                future_weekly_ma10 DOUBLE,
                future_weekly_ma30 DOUBLE
            );
            INSERT INTO weekly_source VALUES
                (DATE '2024-05-31', '1', '01', 99, 100, 100,
                 DATE '{h_date}', 11, 101, 100);
            """
        )
        return con

    def test_parameter_grid_has_four_tolerances(self):
        grid = build_gh_parameter_grid()
        self.assertEqual(grid["weekly_ma_tolerance_pct"].tolist(), [1, 2, 3, 4])

    def test_g_checks_clustering_and_h_checks_crossover(self):
        con = self.create_source()
        create_gh_coverage_tables(con, weekly_path="weekly_source")
        result = con.execute(
            """
            SELECT g_date, h_confirmation_date, flag_g, flag_h
            FROM gh_selections
            WHERE parameter_name = 'gh_tol1'
            """
        ).fetchone()
        self.assertEqual(result, (date(2024, 5, 31), date(2024, 6, 7), True, True))

    def test_g_does_not_check_orientation(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE weekly_source (
                week_end_date DATE, gvkey VARCHAR, iid VARCHAR,
                weekly_ma5 DOUBLE, weekly_ma10 DOUBLE, weekly_ma30 DOUBLE,
                future_weekly_confirmation_date DATE, future_weekly_close_price DOUBLE,
                future_weekly_ma10 DOUBLE, future_weekly_ma30 DOUBLE
            );
            INSERT INTO weekly_source VALUES
                (DATE '2024-05-31', '1', '01', 100, 100.5, 100,
                 DATE '2024-06-07', 11, 101, 100);
            """
        )
        create_gh_coverage_tables(con, weekly_path="weekly_source")
        result = con.execute(
            "SELECT flag_g, flag_h FROM gh_security_evaluation WHERE parameter_name = 'gh_tol1'"
        ).fetchone()
        self.assertEqual(result, (True, False))

    def test_coverage_count_is_attributed_to_g_date(self):
        con = self.create_source()
        create_gh_coverage_tables(con, weekly_path="weekly_source")
        result = con.execute(
            """
            SELECT evaluation_date, selected_company_count
            FROM gh_weekly_coverage
            WHERE parameter_name = 'gh_tol1'
            """
        ).fetchone()
        self.assertEqual(result, (date(2024, 5, 31), 1))

    def test_missing_immediately_following_week_expires_g(self):
        con = self.create_source(h_date="2024-06-14")
        create_gh_coverage_tables(con, weekly_path="weekly_source")
        selected = con.execute("SELECT COUNT(*) FROM gh_selections").fetchone()[0]
        self.assertEqual(selected, 0)


if __name__ == "__main__":
    unittest.main()

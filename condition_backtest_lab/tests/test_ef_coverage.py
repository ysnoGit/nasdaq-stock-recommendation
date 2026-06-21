from datetime import date
import unittest

import duckdb

from condition_backtest_lab.src.ef_coverage import (
    build_ef_parameter_grid,
    create_ef_coverage_tables,
)


class EFCoverageTest(unittest.TestCase):
    def create_source(self, confirmation_date: str = "2024-05-28") -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute(
            f"""
            CREATE TABLE daily_source (
                snapshot_date DATE,
                gvkey VARCHAR,
                iid VARCHAR,
                ticker VARCHAR,
                company_name VARCHAR,
                adjusted_close_price DOUBLE,
                ma20 DOUBLE,
                ma50 DOUBLE,
                ma100 DOUBLE
            );
            INSERT INTO daily_source VALUES
                (DATE '2024-05-24', '1', '01', 'ONE', 'One Co', 10, 99, 100, 100),
                (DATE '{confirmation_date}', '1', '01', 'ONE', 'One Co', 11, 150, 100, 300);
            """
        )
        return con

    def test_parameter_grid_has_three_tolerances(self):
        grid = build_ef_parameter_grid()
        self.assertEqual(grid["daily_ma_tolerance_pct"].tolist(), [1, 2, 3])

    def test_holiday_weekend_maps_to_next_official_session(self):
        con = self.create_source()
        create_ef_coverage_tables(con, daily_path="daily_source")
        result = con.execute(
            """
            SELECT e_date, f_confirmation_date
            FROM ef_selections
            WHERE parameter_name = 'ef_tol1'
            """
        ).fetchone()
        self.assertEqual(result, (date(2024, 5, 24), date(2024, 5, 28)))

    def test_f_does_not_recheck_clustering(self):
        con = self.create_source()
        create_ef_coverage_tables(con, daily_path="daily_source")
        selected = con.execute(
            "SELECT COUNT(*) FROM ef_selections WHERE parameter_name = 'ef_tol1'"
        ).fetchone()[0]
        self.assertEqual(selected, 1)

    def test_coverage_count_is_attributed_to_e_date(self):
        con = self.create_source()
        create_ef_coverage_tables(con, daily_path="daily_source")
        result = con.execute(
            """
            SELECT evaluation_date, selected_company_count
            FROM ef_daily_coverage
            WHERE parameter_name = 'ef_tol1'
            """
        ).fetchone()
        self.assertEqual(result, (date(2024, 5, 24), 1))

    def test_e_checks_clustering_without_orientation(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE daily_source (
                snapshot_date DATE,
                gvkey VARCHAR,
                iid VARCHAR,
                ticker VARCHAR,
                company_name VARCHAR,
                adjusted_close_price DOUBLE,
                ma20 DOUBLE,
                ma50 DOUBLE,
                ma100 DOUBLE
            );
            INSERT INTO daily_source VALUES
                (DATE '2024-05-24', '1', '01', 'ONE', 'One Co', 10, 100.5, 100, 100),
                (DATE '2024-05-28', '1', '01', 'ONE', 'One Co', 11, 150, 100, 300);
            """
        )
        create_ef_coverage_tables(con, daily_path="daily_source")
        result = con.execute(
            """
            SELECT flag_e, flag_f
            FROM ef_security_evaluation
            WHERE parameter_name = 'ef_tol1'
            """
        ).fetchone()
        self.assertEqual(result, (True, False))

    def test_missing_immediate_official_session_expires_e(self):
        con = self.create_source(confirmation_date="2024-05-29")
        create_ef_coverage_tables(con, daily_path="daily_source")
        selected = con.execute("SELECT COUNT(*) FROM ef_selections").fetchone()[0]
        self.assertEqual(selected, 0)


if __name__ == "__main__":
    unittest.main()

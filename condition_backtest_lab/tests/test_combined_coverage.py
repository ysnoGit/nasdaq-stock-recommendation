from datetime import date
import unittest

import duckdb

from condition_backtest_lab.src.combined_coverage import (
    combined_grid,
    create_cdef_coverage_tables,
    create_cdgh_coverage_tables,
)
from condition_backtest_lab.src.ef_coverage import DAILY_MA_TOLERANCE_PCT
from condition_backtest_lab.src.gh_coverage import WEEKLY_MA_TOLERANCE_PCT


def create_daily_source(con: duckdb.DuckDBPyConnection, securities: tuple[str, ...]) -> None:
    con.execute(
        """
        CREATE TABLE daily_source (
            snapshot_date DATE,
            gvkey VARCHAR,
            iid VARCHAR,
            ticker VARCHAR,
            company_name VARCHAR,
            adjusted_close_price DOUBLE,
            volume DOUBLE,
            volume_ma30 DOUBLE,
            volume_ratio DOUBLE,
            ma20 DOUBLE,
            ma50 DOUBLE,
            ma100 DOUBLE
        )
        """
    )
    for gvkey in securities:
        con.execute(
            f"""
            INSERT INTO daily_source
            SELECT
                DATE '2024-01-01' + CAST(i * 4 AS INTEGER),
                '{gvkey}', '01', 'T{gvkey}', 'Company {gvkey}',
                NULL, 500, 100, 5, NULL, NULL, NULL
            FROM range(30) t(i)
            """
        )
        con.execute(
            f"""
            INSERT INTO daily_source VALUES
                (DATE '2024-05-28', '{gvkey}', '01', 'T{gvkey}', 'Company {gvkey}',
                 10, 500, 100, 5, 99, 100, 100),
                (DATE '2024-05-29', '{gvkey}', '01', 'T{gvkey}', 'Company {gvkey}',
                 11, 500, 100, 5, 101, 100, 100),
                (DATE '2024-05-30', '{gvkey}', '01', 'T{gvkey}', 'Company {gvkey}',
                 12, 500, 100, 5, 101, 100, 100),
                (DATE '2024-05-31', '{gvkey}', '01', 'T{gvkey}', 'Company {gvkey}',
                 13, 500, 100, 5, 101, 100, 100)
            """
        )


class CombinedCoverageTest(unittest.TestCase):
    def test_cdef_grid_has_54_combinations(self):
        grid = combined_grid(DAILY_MA_TOLERANCE_PCT, "ef")
        self.assertEqual(len(grid), 54)
        self.assertEqual(grid["parameter_name"].nunique(), 54)

    def test_cdgh_grid_has_72_combinations(self):
        grid = combined_grid(WEEKLY_MA_TOLERANCE_PCT, "gh")
        self.assertEqual(len(grid), 72)
        self.assertEqual(grid["parameter_name"].nunique(), 72)

    def test_cdef_coverage_is_attributed_to_shared_signal_date(self):
        con = duckdb.connect()
        create_daily_source(con, ("1",))
        create_cdef_coverage_tables(con, daily_path="daily_source")

        result = con.execute(
            """
            SELECT evaluation_date, selected_company_count
            FROM cdef_coverage
            WHERE parameter_name = 'cdef_vr4_vd3_tol1'
              AND selected_company_count > 0
            """
        ).fetchone()
        self.assertEqual(result, (date(2024, 5, 28), 1))

    def test_cdgh_applies_weekly_gate_only_on_official_week_end(self):
        con = duckdb.connect()
        create_daily_source(con, ("1", "2"))
        con.execute(
            """
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
                 DATE '2024-06-07', 11, 101, 100),
                (DATE '2024-05-31', '2', '01', 90, 100, 100,
                 DATE '2024-06-07', 11, 101, 100);
            """
        )
        create_cdgh_coverage_tables(
            con,
            daily_path="daily_source",
            weekly_path="weekly_source",
        )

        counts = con.execute(
            """
            SELECT evaluation_date, selected_company_count
            FROM cdgh_coverage
            WHERE parameter_name = 'cdgh_vr4_vd3_tol1'
              AND evaluation_date IN (DATE '2024-05-30', DATE '2024-05-31')
            ORDER BY evaluation_date
            """
        ).fetchall()
        self.assertEqual(counts, [(date(2024, 5, 30), 2), (date(2024, 5, 31), 1)])

        selections = con.execute(
            """
            SELECT signal_date, weekly_gate_applied, confirmation_date, COUNT(*)
            FROM cdgh_selections
            WHERE parameter_name = 'cdgh_vr4_vd3_tol1'
              AND signal_date IN (DATE '2024-05-30', DATE '2024-05-31')
            GROUP BY ALL
            ORDER BY signal_date
            """
        ).fetchall()
        self.assertEqual(
            selections,
            [
                (date(2024, 5, 30), False, date(2024, 5, 30), 2),
                (date(2024, 5, 31), True, date(2024, 6, 7), 1),
            ],
        )


if __name__ == "__main__":
    unittest.main()

import unittest

import duckdb


class CompleteDailyWindowTest(unittest.TestCase):
    def test_incomplete_windows_remain_null(self):
        con = duckdb.connect()
        con.execute(
            """
            CREATE TABLE prices AS
            SELECT
                CAST(day AS DATE) AS snapshot_date,
                '1' AS gvkey,
                '01' AS iid,
                row_number() OVER (ORDER BY day)::DOUBLE AS adjusted_close_price,
                100::DOUBLE AS volume
            FROM generate_series(
                DATE '2020-01-01', DATE '2020-04-30', INTERVAL 1 DAY
            ) dates(day);
            """
        )
        result = con.execute(
            """
            WITH indicators AS (
                SELECT
                    *,
                    CASE WHEN COUNT(adjusted_close_price) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) = 20 THEN AVG(adjusted_close_price) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                    ) END AS ma20,
                    CASE WHEN COUNT(adjusted_close_price) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
                    ) = 50 THEN AVG(adjusted_close_price) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
                    ) END AS ma50,
                    CASE WHEN COUNT(adjusted_close_price) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 99 PRECEDING AND CURRENT ROW
                    ) = 100 THEN AVG(adjusted_close_price) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 99 PRECEDING AND CURRENT ROW
                    ) END AS ma100,
                    CASE WHEN COUNT(volume) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
                    ) = 30 THEN AVG(volume) OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                        ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
                    ) END AS volume_ma30,
                    row_number() OVER (
                        PARTITION BY gvkey, iid ORDER BY snapshot_date
                    ) AS row_number
                FROM prices
            )
            SELECT row_number, ma20, ma50, ma100, volume_ma30
            FROM indicators
            WHERE row_number IN (19, 20, 30, 31, 49, 50, 99, 100)
            ORDER BY row_number
            """
        ).fetchall()
        by_row = {row[0]: row[1:] for row in result}
        self.assertIsNone(by_row[19][0])
        self.assertIsNotNone(by_row[20][0])
        self.assertIsNone(by_row[49][1])
        self.assertIsNotNone(by_row[50][1])
        self.assertIsNone(by_row[99][2])
        self.assertIsNotNone(by_row[100][2])
        self.assertIsNone(by_row[30][3])
        self.assertIsNotNone(by_row[31][3])


if __name__ == "__main__":
    unittest.main()

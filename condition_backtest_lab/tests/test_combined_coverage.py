import unittest

from condition_backtest_lab.src.combined_coverage import combined_grid
from condition_backtest_lab.src.ef_coverage import DAILY_MA_TOLERANCE_PCT
from condition_backtest_lab.src.gh_coverage import WEEKLY_MA_TOLERANCE_PCT


class CombinedCoverageTest(unittest.TestCase):
    def test_cdef_grid_has_54_combinations(self):
        grid = combined_grid(DAILY_MA_TOLERANCE_PCT, "ef")
        self.assertEqual(len(grid), 54)
        self.assertEqual(grid["parameter_name"].nunique(), 54)

    def test_cdgh_grid_has_72_combinations(self):
        grid = combined_grid(WEEKLY_MA_TOLERANCE_PCT, "gh")
        self.assertEqual(len(grid), 72)
        self.assertEqual(grid["parameter_name"].nunique(), 72)


if __name__ == "__main__":
    unittest.main()

import unittest

from condition_backtest_lab.src.config import DEFAULT_START_DATE
from condition_backtest_lab.src.condition_contracts import CONDITION_CONTRACTS
from condition_backtest_lab.src.screen_types import SCREEN_DEFINITIONS, ScreenType


class ScreenRegistryTest(unittest.TestCase):
    def test_registry_has_exactly_the_requested_six_screens(self):
        self.assertEqual(set(SCREEN_DEFINITIONS), set(ScreenType))
        self.assertEqual(len(SCREEN_DEFINITIONS), 6)

    def test_screen_condition_groups(self):
        expected = {
            ScreenType.A_B: ("A", "B"),
            ScreenType.C_D: ("C", "D"),
            ScreenType.E_F: ("E", "F"),
            ScreenType.G_H: ("G", "H"),
            ScreenType.C_D_E_F: ("C", "D", "E", "F"),
            ScreenType.C_D_G_H: ("C", "D", "G", "H"),
        }
        actual = {
            screen_type: definition.conditions
            for screen_type, definition in SCREEN_DEFINITIONS.items()
        }
        self.assertEqual(actual, expected)

    def test_all_condition_contracts_are_defined(self):
        self.assertEqual(set(CONDITION_CONTRACTS), set("ABCDEFGH"))

    def test_all_requested_screen_studies_are_implemented(self):
        self.assertTrue(
            all(definition.implemented for definition in SCREEN_DEFINITIONS.values())
        )

    def test_ab_coverage_is_implemented(self):
        self.assertTrue(SCREEN_DEFINITIONS[ScreenType.A_B].coverage_implemented)

    def test_cd_coverage_is_implemented(self):
        self.assertTrue(SCREEN_DEFINITIONS[ScreenType.C_D].coverage_implemented)

    def test_ef_coverage_is_implemented(self):
        self.assertTrue(SCREEN_DEFINITIONS[ScreenType.E_F].coverage_implemented)

    def test_gh_coverage_is_implemented(self):
        self.assertTrue(SCREEN_DEFINITIONS[ScreenType.G_H].coverage_implemented)

    def test_combined_coverage_is_implemented(self):
        self.assertTrue(SCREEN_DEFINITIONS[ScreenType.C_D_E_F].coverage_implemented)
        self.assertTrue(SCREEN_DEFINITIONS[ScreenType.C_D_G_H].coverage_implemented)

    def test_default_backtest_range_starts_in_2020(self):
        self.assertEqual(DEFAULT_START_DATE, "2020-01-01")


if __name__ == "__main__":
    unittest.main()

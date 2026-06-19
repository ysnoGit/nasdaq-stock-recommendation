from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScreenType(str, Enum):
    A_B = "A_B"
    C_D = "C_D"
    E_F = "E_F"
    G_H = "G_H"
    C_D_E_F = "C_D_E_F"
    C_D_G_H = "C_D_G_H"


@dataclass(frozen=True)
class ScreenDefinition:
    screen_type: ScreenType
    label: str
    conditions: tuple[str, ...]
    proposed_anchor: str
    actionable_timing: str
    coverage_implemented: bool = False
    implemented: bool = False


SCREEN_DEFINITIONS = {
    ScreenType.A_B: ScreenDefinition(
        ScreenType.A_B,
        "Fundamental growth",
        ("A", "B"),
        "Daily signal date",
        "Pending confirmation: same-day action or another entry rule.",
        coverage_implemented=True,
        implemented=True,
    ),
    ScreenType.C_D: ScreenDefinition(
        ScreenType.C_D,
        "Volume activity",
        ("C", "D"),
        "Daily signal date",
        "Pending confirmation: same-day action or another entry rule.",
        coverage_implemented=True,
        implemented=True,
    ),
    ScreenType.E_F: ScreenDefinition(
        ScreenType.E_F,
        "Daily MA setup and crossover",
        ("E", "F"),
        "E daily signal date",
        "F confirmation on the immediately following official market session.",
        coverage_implemented=True,
        implemented=True,
    ),
    ScreenType.G_H: ScreenDefinition(
        ScreenType.G_H,
        "Weekly MA setup and crossover",
        ("G", "H"),
        "Every eligible completed official trading week",
        "H confirmation on the completed official week following G.",
        coverage_implemented=True,
        implemented=True,
    ),
    ScreenType.C_D_E_F: ScreenDefinition(
        ScreenType.C_D_E_F,
        "Volume plus daily MA confirmation",
        ("C", "D", "E", "F"),
        "Shared C/D/E daily signal date",
        "F confirmation on the immediately following official market session.",
        coverage_implemented=True,
        implemented=True,
    ),
    ScreenType.C_D_G_H: ScreenDefinition(
        ScreenType.C_D_G_H,
        "Volume plus weekly MA confirmation",
        ("C", "D", "G", "H"),
        "C/D daily signal anchors the first completed week on/after it",
        "H confirmation on the completed official week following G.",
        coverage_implemented=True,
        implemented=True,
    ),
}


def get_screen_definition(value: str | ScreenType) -> ScreenDefinition:
    return SCREEN_DEFINITIONS[ScreenType(value)]

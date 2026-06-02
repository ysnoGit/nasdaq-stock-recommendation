from __future__ import annotations

import re

import pandas as pd


UNIVERSE_EXCLUSION_RULES = [
    (
        "redeemable marker",
        re.compile(r"(^|\s)-REDH\b|\bREDH\b", re.IGNORECASE),
    ),
    (
        "redeemable security",
        re.compile(r"\bREDEEM(?:ABLE)?\b", re.IGNORECASE),
    ),
    (
        "warrant security",
        re.compile(r"\bWARRANTS?\b", re.IGNORECASE),
    ),
    (
        "rights security",
        re.compile(r"\bRIGHTS?\b", re.IGNORECASE),
    ),
    (
        "unit security",
        re.compile(r"\bUNITS?\b", re.IGNORECASE),
    ),
    (
        "SPAC/acquisition company",
        re.compile(
            r"\bACQUISITION\b|\bACQ(?:\.|\s|$)|\bACQUTN\b|\bBLANK CHECK\b|\bSPAC\b",
            re.IGNORECASE,
        ),
    ),
]


def universe_search_text(row: pd.Series) -> str:
    parts = [
        row.get("ticker"),
        row.get("company_name"),
        row.get("iid"),
    ]
    return " ".join("" if pd.isna(value) else str(value) for value in parts)


def universe_exclusion_reasons(row: pd.Series) -> list[str]:
    text = universe_search_text(row)
    return [
        reason
        for reason, pattern in UNIVERSE_EXCLUSION_RULES
        if pattern.search(text)
    ]


def add_universe_filter_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    reasons = df.apply(universe_exclusion_reasons, axis=1)
    df["exclusion_reason"] = reasons.apply(lambda items: "; ".join(items))
    df["is_excluded_universe"] = df["exclusion_reason"] != ""
    return df

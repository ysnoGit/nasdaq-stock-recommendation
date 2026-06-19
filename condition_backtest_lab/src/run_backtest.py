from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

from condition_backtest_lab.src.config import DAILY_FEATURE_PATH, WEEKLY_FEATURE_PATH
from condition_backtest_lab.src.screen_types import SCREEN_DEFINITIONS, ScreenType


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def list_screen_types() -> None:
    for definition in SCREEN_DEFINITIONS.values():
        if definition.implemented:
            status = "implemented"
        elif definition.coverage_implemented:
            status = "coverage implemented; performance awaits specification"
        else:
            status = "awaiting detailed specification"
        print(
            f"{definition.screen_type.value}: {', '.join(definition.conditions)} "
            f"| {definition.label} | {status}"
        )


def summarize_parquet(path: Path, date_column: str) -> str:
    if not path.exists():
        return f"MISSING: {path}"
    con = duckdb.connect()
    try:
        row = con.execute(
            f"""
            SELECT COUNT(*), MIN({date_column}), MAX({date_column}),
                   COUNT(DISTINCT (gvkey, iid))
            FROM read_parquet('{sql_path(path)}')
            """
        ).fetchone()
    finally:
        con.close()
    return (
        f"OK: {path} | rows={row[0]:,} | dates={row[1]} to {row[2]} "
        f"| securities={row[3]:,}"
    )


def check_environment() -> bool:
    summaries = (
        summarize_parquet(DAILY_FEATURE_PATH, "snapshot_date"),
        summarize_parquet(WEEKLY_FEATURE_PATH, "week_end_date"),
    )
    for summary in summaries:
        print(summary)
    return all(summary.startswith("OK:") for summary in summaries)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Condition-group backtest lab")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list-screen-types", action="store_true")
    action.add_argument("--check-environment", action="store_true")
    action.add_argument("--screen-type", choices=[item.value for item in ScreenType])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_screen_types:
        list_screen_types()
        return
    if args.check_environment:
        if not check_environment():
            raise SystemExit(1)
        return

    definition = SCREEN_DEFINITIONS[ScreenType(args.screen_type)]
    if not definition.implemented:
        raise SystemExit(
            f"{definition.screen_type.value} is registered but execution is disabled "
            "until its detailed selection, entry, parameter, and deduplication rules "
            "are confirmed."
        )


if __name__ == "__main__":
    main()

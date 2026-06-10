from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from backtest_lab.src.config import ROOT
from backtest_lab.src.db import connect_supabase


DEFAULT_JSON = ROOT / "reports" / "performance_comparison.json"
DEFAULT_CSV = ROOT / "reports" / "performance_comparison.csv"
EXPECTED_PARAMETER_SETS_PER_SCREEN = 192


def serialize(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the complete A-F/A-H performance comparison from Supabase."
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    query = (ROOT / "sql" / "export_performance_comparison.sql").read_text(
        encoding="utf-8"
    )
    with connect_supabase() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            columns = [column.name for column in cur.description]
            rows = [
                {column: serialize(value) for column, value in zip(columns, row)}
                for row in cur.fetchall()
            ]

    counts = {}
    for row in rows:
        counts[row["screen_type"]] = counts.get(row["screen_type"], 0) + 1

    expected = {"A_F", "A_H"}
    if set(counts) != expected:
        raise RuntimeError(
            f"Expected both A_F and A_H rows, found screen types: {sorted(counts)}"
        )
    incomplete = {
        screen: count
        for screen, count in counts.items()
        if count != EXPECTED_PARAMETER_SETS_PER_SCREEN
    }
    if incomplete:
        raise RuntimeError(
            "Performance export is incomplete. Expected "
            f"{EXPECTED_PARAMETER_SETS_PER_SCREEN} parameter sets per screen, "
            f"found: {incomplete}"
        )
    horizon_fields = {
        f"{metric}_{horizon}{suffix}"
        for horizon in ("6m", "1y", "2y")
        for metric, suffix in (
            ("sample_size", ""),
            ("avg_return", "_pct"),
            ("median_return", "_pct"),
            ("win_rate", "_pct"),
        )
    }
    missing_fields = horizon_fields - set(rows[0])
    if missing_fields:
        raise RuntimeError(
            f"Performance export is missing fixed-horizon fields: {sorted(missing_fields)}"
        )
    if not any(row["sample_size_6m"] for row in rows):
        raise RuntimeError(
            "Performance export contains no completed 6-month outcomes. "
            "Rerun the backtest after applying the fixed-horizon schema."
        )

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with args.csv_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported rows: {len(rows):,}")
    print(f"Rows by screen: {counts}")
    print(f"JSON: {args.json_output}")
    print(f"CSV: {args.csv_output}")


if __name__ == "__main__":
    main()

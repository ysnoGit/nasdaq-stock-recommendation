from __future__ import annotations

from pathlib import Path

from backtest_lab.src.config import ROOT
from backtest_lab.src.db import connect_supabase


def main() -> None:
    statements = [
        statement.strip()
        for statement in (ROOT / "sql" / "validate_backtest_results.sql")
        .read_text(encoding="utf-8")
        .split(";")
        if statement.strip()
    ]
    with connect_supabase() as conn:
        with conn.cursor() as cur:
            for index, statement in enumerate(statements, start=1):
                cur.execute(statement)
                print(f"\nValidation result {index}")
                print([column.name for column in cur.description])
                for row in cur.fetchall():
                    print(row)


if __name__ == "__main__":
    main()

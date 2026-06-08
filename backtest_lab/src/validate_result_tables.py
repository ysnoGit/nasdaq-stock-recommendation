from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.db import connect_supabase  # noqa: E402
from backtest_lab.src.parameter_grid import parameter_grid  # noqa: E402


def main() -> None:
    with connect_supabase() as conn:
        with conn.cursor() as cur:
            print("\nBacktest grid result tables")
            for combo in parameter_grid():
                table_name = combo.result_table_name
                cur.execute("SELECT to_regclass(%s)", (table_name,))
                exists = cur.fetchone()[0] is not None
                if not exists:
                    print(f"{table_name}: MISSING")
                    continue

                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = int(cur.fetchone()[0])
                print(f"{table_name}: {row_count:,} rows")


if __name__ == "__main__":
    main()

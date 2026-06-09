#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -d venv ]] && source venv/bin/activate
python3 - <<'PY'
from backtest_lab.src.config import ROOT
from backtest_lab.src.db import connect_supabase, execute_sql_file
with connect_supabase() as conn:
    execute_sql_file(conn, ROOT / "sql" / "create_backtest_tables.sql")
print("Backtest schema applied.")
PY

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT"

if [[ -d venv ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

if [[ "${BACKTEST_ALLOW_SUPABASE_FEATURE_LOAD:-}" != "true" ]]; then
  cat >&2 <<'EOF'
Refusing to load historical backtest daily/weekly feature tables into Supabase.

The full 2022+ feature load creates millions of rows and can exhaust Supabase
database storage. Use the storage-light S3/DuckDB runner instead:

  bash backtest_lab/scripts/run_backtest_pipeline.sh --start-date 2022-01-01

To intentionally run the old feature-table loader for a small debug window, set:

  export BACKTEST_ALLOW_SUPABASE_FEATURE_LOAD=true

EOF
  exit 2
fi

python3 -m backtest_lab.src.load_backtest_tables "$@"

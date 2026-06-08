#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "$REPO_ROOT"

if [[ -d venv ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

python3 -m backtest_lab.src.run_backtest_selection "$@"
python3 -m backtest_lab.src.generate_price_flow_3m "$@"
python3 -m backtest_lab.src.materialize_result_tables "$@"

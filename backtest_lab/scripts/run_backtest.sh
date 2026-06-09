#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -d venv ]] && source venv/bin/activate
python3 -m backtest_lab.src.run_backtest --apply-schema "$@"

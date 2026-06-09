#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -d venv ]] && source venv/bin/activate
python3 - <<'PY'
from backtest_lab.src.cleanup import cleanup_generated_outputs
cleanup_generated_outputs()
print("Generated local backtest outputs cleaned.")
PY

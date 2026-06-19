#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

[[ -d venv ]] && source venv/bin/activate
python3 -m condition_backtest_lab.src.cd_coverage "$@"

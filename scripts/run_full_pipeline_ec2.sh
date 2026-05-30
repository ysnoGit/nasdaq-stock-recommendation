#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/projects/nasdaq-stock-recommendation}"

cd "$REPO_ROOT"

if [[ ! -d "venv" ]]; then
  echo "Virtual environment not found: $REPO_ROOT/venv" >&2
  exit 1
fi

source venv/bin/activate

if [[ -z "${WRDS_USERNAME:-}" ]]; then
  echo 'WRDS_USERNAME is not set. Run:' >&2
  echo 'export WRDS_USERNAME="your_wrds_username"' >&2
  exit 1
fi

if [[ ! -f "$HOME/.pgpass" ]]; then
  echo "WRDS .pgpass file is missing. Expected file path: $HOME/.pgpass" >&2
  exit 1
fi

pgpass_mode="$(stat -c '%a' "$HOME/.pgpass")"
if [[ "$pgpass_mode" != "600" ]]; then
  echo "WRDS .pgpass permission is unsafe: $pgpass_mode" >&2
  echo "Run: chmod 600 ~/.pgpass" >&2
  exit 1
fi

python3 server_pipeline/run_full_pipeline.py "$@"

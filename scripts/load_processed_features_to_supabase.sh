#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/projects/nasdaq-stock-recommendation}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-2}}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
export AWS_REGION AWS_DEFAULT_REGION

cd "$REPO_ROOT"

if [[ ! -d "venv" ]]; then
  echo "Virtual environment not found: $REPO_ROOT/venv" >&2
  exit 1
fi

source venv/bin/activate

if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
  echo 'SUPABASE_DB_URL is not set. Run:' >&2
  echo 'export SUPABASE_DB_URL="postgresql://..."' >&2
  exit 1
fi

python3 server_pipeline/serving/load_processed_features_to_supabase.py "$@"

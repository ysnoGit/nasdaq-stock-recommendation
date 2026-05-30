#!/usr/bin/env bash
set -euo pipefail

S3_BUCKET="${S3_BUCKET:-nasdaq-stock-recommendation}"

echo "Python:"
python3 --version

echo
echo "pip:"
python3 -m pip --version

echo
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  echo "venv active: $VIRTUAL_ENV"
else
  echo "venv active: no"
fi

echo
echo "Python package imports:"
python3 - <<'PY'
packages = ["wrds", "pandas", "boto3", "pyarrow", "duckdb"]
for package in packages:
    try:
        __import__(package)
    except Exception as exc:
        print(f"FAIL {package}: {exc}")
        raise
    else:
        print(f"OK   {package}")
PY

echo
if [[ -n "${WRDS_USERNAME:-}" ]]; then
  echo "WRDS_USERNAME: set"
else
  echo 'WRDS_USERNAME is not set. Run: export WRDS_USERNAME="your_wrds_username"' >&2
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
echo ".pgpass: present with safe permissions"

echo
echo "AWS identity:"
aws sts get-caller-identity

echo
echo "S3 bucket access:"
aws s3 ls "s3://${S3_BUCKET}/"

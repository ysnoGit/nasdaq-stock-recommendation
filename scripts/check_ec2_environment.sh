#!/usr/bin/env bash
set -euo pipefail

S3_BUCKET="${S3_BUCKET:-nasdaq-stock-recommendation}"
AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-2}}"
AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
export AWS_REGION AWS_DEFAULT_REGION

echo "Python:"
python3 --version

echo
echo "pip:"
python3 -m pip --version

echo
echo "AWS region:"
echo "AWS_REGION=$AWS_REGION"
echo "AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION"

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
echo "S3 bucket region:"
bucket_region="$(aws s3api get-bucket-location --bucket "$S3_BUCKET" --output text)"
if [[ "$bucket_region" == "None" ]]; then
  bucket_region="us-east-1"
fi
echo "s3://${S3_BUCKET}: $bucket_region"
if [[ "$bucket_region" != "$AWS_REGION" ]]; then
  echo "Bucket region does not match configured AWS region: $AWS_REGION" >&2
  exit 1
fi

echo
echo "S3 bucket access:"
aws s3 ls "s3://${S3_BUCKET}/" --region "$AWS_REGION"

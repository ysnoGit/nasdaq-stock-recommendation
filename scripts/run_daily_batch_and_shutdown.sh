#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/ec2-user/projects/nasdaq-stock-recommendation"
ENV_FILE="/home/ec2-user/.nasdaq_pipeline.env"
LOG_DIR="${REPO_DIR}/logs"
TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="${LOG_DIR}/daily_batch_${TIMESTAMP}.log"

mkdir -p "${LOG_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

EXIT_CODE=0
CALLER_AUTO_STOP_EC2="${AUTO_STOP_EC2:-}"

get_imdsv2_token() {
  curl -fsS -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
    --connect-timeout 2 \
    --max-time 5
}

get_instance_id() {
  local token="$1"
  curl -fsS "http://169.254.169.254/latest/meta-data/instance-id" \
    -H "X-aws-ec2-metadata-token: ${token}" \
    --connect-timeout 2 \
    --max-time 5
}

maybe_stop_instance() {
  local code="$1"
  echo
  echo "Daily batch finished with exit code: ${code}"
  echo "Log file: ${LOG_FILE}"

  if [[ "${AUTO_STOP_EC2:-false}" != "true" ]]; then
    echo "AUTO_STOP_EC2 is not true; leaving EC2 instance running."
    return
  fi

  echo "AUTO_STOP_EC2=true; attempting to stop the current EC2 instance."

  local token
  if ! token="$(get_imdsv2_token)"; then
    echo "Could not get IMDSv2 token. This may be a local/non-EC2 run; skipping shutdown."
    return
  fi

  local instance_id
  if ! instance_id="$(get_instance_id "${token}")"; then
    echo "Could not get EC2 instance ID from metadata; skipping shutdown."
    return
  fi

  local region="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-northeast-2}}"
  echo "Stopping EC2 instance ${instance_id} in ${region}."
  aws ec2 stop-instances \
    --instance-ids "${instance_id}" \
    --region "${region}" \
    --output text \
    || echo "WARNING: EC2 stop-instances command failed."
}

on_exit() {
  EXIT_CODE=$?
  maybe_stop_instance "${EXIT_CODE}"
}
trap on_exit EXIT

echo "NASDAQ daily batch started at $(date -Is)"
echo "Repository: ${REPO_DIR}"
echo "Environment file: ${ENV_FILE}"

cd "${REPO_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Required environment file is missing: ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

if [[ -n "${CALLER_AUTO_STOP_EC2}" ]]; then
  export AUTO_STOP_EC2="${CALLER_AUTO_STOP_EC2}"
  echo "AUTO_STOP_EC2 overridden by caller."
fi

echo "AWS_REGION=${AWS_REGION:-unset}"
echo "AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-unset}"
echo "AUTO_STOP_EC2=${AUTO_STOP_EC2:-unset}"
echo "WRDS_USERNAME: ${WRDS_USERNAME:+set}"
echo "SUPABASE_DB_URL: ${SUPABASE_DB_URL:+set}"

if [[ ! -d "venv" ]]; then
  echo "Virtual environment not found: ${REPO_DIR}/venv" >&2
  exit 1
fi

source venv/bin/activate

echo
echo "Pulling latest code..."
git pull origin main

echo
echo "Compiling server pipeline..."
python3 -m compileall server_pipeline

echo
echo "Checking EC2 environment..."
bash scripts/check_ec2_environment.sh

echo
echo "Running full WRDS + S3 pipeline..."
python3 server_pipeline/run_full_pipeline.py

echo
echo "Loading processed features into Supabase..."
bash scripts/load_processed_features_to_supabase.sh

echo
echo "Validating Supabase row counts..."
python3 - <<'PY'
import os

import psycopg

tables = [
    "security_master",
    "security_daily_feature_snapshot",
    "security_weekly_feature_snapshot",
    "annual_growth_history",
    "quarterly_growth_history",
]

with psycopg.connect(os.environ["SUPABASE_DB_URL"]) as conn:
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"{table}: {cur.fetchone()[0]:,} rows")

        cur.execute("""
            SELECT
                MIN(snapshot_date) AS min_snapshot_date,
                MAX(snapshot_date) AS max_snapshot_date,
                COUNT(*) AS row_count,
                COUNT(*) FILTER (WHERE volume_ratio IS NOT NULL) AS volume_ratio_rows
            FROM security_daily_feature_snapshot
        """)
        min_date, max_date, row_count, volume_rows = cur.fetchone()
        print(
            "security_daily_feature_snapshot coverage: "
            f"{min_date} to {max_date}; rows={row_count:,}; "
            f"volume_ratio_rows={volume_rows:,}"
        )

        cur.execute("""
            SELECT
                MIN(week_end_date) AS min_week_end_date,
                MAX(week_end_date) AS max_week_end_date,
                COUNT(*) AS row_count
            FROM security_weekly_feature_snapshot
        """)
        min_week, max_week, weekly_row_count = cur.fetchone()
        print(
            "security_weekly_feature_snapshot coverage: "
            f"{min_week} to {max_week}; rows={weekly_row_count:,}"
        )

        cur.execute("""
            SELECT
                COUNT(DISTINCT snapshot_date) AS distinct_snapshot_dates,
                MAX(snapshot_date) - MIN(snapshot_date) AS covered_days
            FROM security_daily_feature_snapshot
            WHERE snapshot_date >= (
                (SELECT MAX(snapshot_date) FROM security_daily_feature_snapshot)
                - INTERVAL '3 months'
            )
        """)
        distinct_dates, covered_days = cur.fetchone()
        print(
            "dynamic Condition D lookback coverage: "
            f"{distinct_dates:,} snapshot dates across {covered_days} days"
        )

        if distinct_dates == 0:
            raise RuntimeError("security_daily_feature_snapshot has no rows for dynamic Condition D.")

        cur.execute("""
            WITH latest AS (
                SELECT MAX(snapshot_date) AS snapshot_date
                FROM security_daily_feature_snapshot
            )
            SELECT
                COUNT(*) AS latest_rows,
                COUNT(sm.gvkey) AS joined_master_rows
            FROM security_daily_feature_snapshot AS s
            CROSS JOIN latest AS l
            LEFT JOIN security_master AS sm
              ON s.gvkey = sm.gvkey
             AND s.iid = sm.iid
            WHERE s.snapshot_date = l.snapshot_date
        """)
        latest_rows, joined_master_rows = cur.fetchone()
        print(
            "latest snapshot security_master join: "
            f"{joined_master_rows:,}/{latest_rows:,} rows"
        )
        if joined_master_rows < latest_rows:
            raise RuntimeError("Latest security snapshot rows do not all join to security_master.")
PY

echo
echo "Verifying processed S3 outputs..."
aws s3 ls s3://nasdaq-stock-recommendation/processed/ \
  --recursive \
  --human-readable \
  --summarize \
  | tail -20

echo
echo "NASDAQ daily batch completed successfully at $(date -Is)"

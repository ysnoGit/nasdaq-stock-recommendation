#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ec2-user/projects/nasdaq-stock-recommendation}"

cd "${REPO_DIR}"

echo "Running daily batch with AUTO_STOP_EC2=false for this test only."
echo "This does not modify /home/ec2-user/.nasdaq_pipeline.env."

export AUTO_STOP_EC2=false
exec bash scripts/run_daily_batch_and_shutdown.sh

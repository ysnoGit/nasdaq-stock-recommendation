#!/usr/bin/env bash
set -euo pipefail

REGION="ap-northeast-2"
INSTANCE_ID="i-07311259548e90438"
BATCH_COMMAND="runuser -l ec2-user -c 'cd /home/ec2-user/projects/nasdaq-stock-recommendation && bash scripts/run_daily_batch_and_shutdown.sh'"
PARAMETERS_FILE="$(mktemp)"

cleanup() {
  rm -f "${PARAMETERS_FILE}"
}
trap cleanup EXIT

python3 - "${PARAMETERS_FILE}" "${BATCH_COMMAND}" <<'PY'
import json
import sys

parameters_file, batch_command = sys.argv[1:]
with open(parameters_file, "w", encoding="utf-8") as handle:
    json.dump({"commands": [batch_command]}, handle)
PY

echo "Sending SSM Run Command to ${INSTANCE_ID}..."
COMMAND_ID="$(
  aws ssm send-command \
    --region "${REGION}" \
    --instance-ids "${INSTANCE_ID}" \
    --document-name "AWS-RunShellScript" \
    --comment "Run NASDAQ daily batch" \
    --parameters "file://${PARAMETERS_FILE}" \
    --query "Command.CommandId" \
    --output text
)"

echo "Command ID: ${COMMAND_ID}"
echo
echo "Check status with:"
echo "  aws ssm list-command-invocations --command-id ${COMMAND_ID} --details --region ${REGION}"

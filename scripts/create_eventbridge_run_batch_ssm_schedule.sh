#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${REPO_DIR:-${DEFAULT_REPO_DIR}}"
REGION="ap-northeast-2"
INSTANCE_ID="i-07311259548e90438"
ROLE_NAME="NasdaqRunBatchSSMSchedulerRole"
POLICY_NAME="RunNasdaqBatchSSMPolicy"
SCHEDULE_NAME="run-nasdaq-daily-batch-ssm-weekdays"
SCHEDULE_EXPRESSION="cron(5 20 ? * TUE-SAT *)"
SCHEDULE_TIMEZONE="Asia/Seoul"
TRUST_POLICY="${REPO_DIR}/infra/iam/eventbridge-scheduler-trust-policy.json"
SSM_POLICY="${REPO_DIR}/infra/iam/eventbridge-ssm-send-command-policy.json"
TARGET_ARN="arn:aws:scheduler:::aws-sdk:ssm:sendCommand"
BATCH_COMMAND="runuser -l ec2-user -c 'cd /home/ec2-user/projects/nasdaq-stock-recommendation && bash scripts/run_daily_batch_and_shutdown.sh'"

print_permission_help() {
  cat >&2 <<EOF

ERROR: SSM batch schedule setup needs one-time IAM/Scheduler permissions.

Run this script from AWS CloudShell or an AWS CLI profile that can manage IAM
roles and EventBridge Scheduler resources.

Required one-time permissions include:
  iam:GetRole
  iam:CreateRole
  iam:UpdateAssumeRolePolicy
  iam:PutRolePolicy
  iam:PassRole
  scheduler:GetSchedule
  scheduler:CreateSchedule
  scheduler:UpdateSchedule

The EC2 instance role must also have AmazonSSMManagedInstanceCore attached so
the instance can receive SSM Run Command requests.
EOF
}

run_or_explain_permissions() {
  if ! "$@"; then
    print_permission_help
    exit 1
  fi
}

run_schedule_command() {
  local attempt
  for attempt in 1 2 3; do
    if "$@"; then
      return 0
    fi

    echo "Schedule command failed on attempt ${attempt}." >&2
    if [[ "${attempt}" -lt 3 ]]; then
      echo "Waiting for IAM role/trust-policy propagation before retrying..." >&2
      sleep 20
    fi
  done

  print_permission_help
  exit 1
}

if [[ ! -f "${TRUST_POLICY}" ]]; then
  echo "Trust policy not found: ${TRUST_POLICY}" >&2
  exit 1
fi

if [[ ! -f "${SSM_POLICY}" ]]; then
  echo "SSM policy not found: ${SSM_POLICY}" >&2
  exit 1
fi

echo "Creating or updating IAM role ${ROLE_NAME}..."
if aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  run_or_explain_permissions aws iam update-assume-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-document "file://${TRUST_POLICY}"
else
  run_or_explain_permissions aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${TRUST_POLICY}"
fi

run_or_explain_permissions aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${POLICY_NAME}" \
  --policy-document "file://${SSM_POLICY}"

ROLE_ARN="$(aws iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)" || {
  print_permission_help
  exit 1
}

echo "Scheduler role ARN: ${ROLE_ARN}"
echo "Waiting for IAM role/trust-policy propagation..."
sleep 20

TARGET_FILE="$(mktemp)"
python3 - "${TARGET_FILE}" "${TARGET_ARN}" "${ROLE_ARN}" "${INSTANCE_ID}" "${BATCH_COMMAND}" <<'PY'
import json
import sys

target_file, target_arn, role_arn, instance_id, batch_command = sys.argv[1:]
input_payload = {
    "DocumentName": "AWS-RunShellScript",
    "InstanceIds": [instance_id],
    "Parameters": {
        "commands": [batch_command],
    },
}
target = {
    "Arn": target_arn,
    "RoleArn": role_arn,
    "Input": json.dumps(input_payload),
}
with open(target_file, "w", encoding="utf-8") as handle:
    json.dump(target, handle)
PY

cleanup() {
  rm -f "${TARGET_FILE}"
}
trap cleanup EXIT

echo "Creating or updating schedule ${SCHEDULE_NAME}..."
if aws scheduler get-schedule --name "${SCHEDULE_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  run_schedule_command aws scheduler update-schedule \
    --name "${SCHEDULE_NAME}" \
    --region "${REGION}" \
    --schedule-expression "${SCHEDULE_EXPRESSION}" \
    --schedule-expression-timezone "${SCHEDULE_TIMEZONE}" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "file://${TARGET_FILE}"
else
  run_schedule_command aws scheduler create-schedule \
    --name "${SCHEDULE_NAME}" \
    --region "${REGION}" \
    --schedule-expression "${SCHEDULE_EXPRESSION}" \
    --schedule-expression-timezone "${SCHEDULE_TIMEZONE}" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "file://${TARGET_FILE}"
fi

echo
echo "EventBridge SSM batch schedule setup complete."
echo "Schedule: ${SCHEDULE_NAME}"
echo "Cron: ${SCHEDULE_EXPRESSION}"
echo "Timezone: ${SCHEDULE_TIMEZONE}"
echo "Target instance: ${INSTANCE_ID}"
echo
echo "Verify with:"
echo "  aws scheduler get-schedule --name ${SCHEDULE_NAME} --region ${REGION}"

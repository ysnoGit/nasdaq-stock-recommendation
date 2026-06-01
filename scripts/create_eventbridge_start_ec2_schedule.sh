#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${REPO_DIR:-${DEFAULT_REPO_DIR}}"
REGION="ap-northeast-2"
INSTANCE_ID="i-07311259548e90438"
ROLE_NAME="NasdaqStartEC2SchedulerRole"
POLICY_NAME="StartNasdaqBatchEC2Policy"
SCHEDULE_NAME="start-nasdaq-batch-ec2-weekdays"
SCHEDULE_EXPRESSION="cron(0 20 ? * TUE-SAT *)"
SCHEDULE_TIMEZONE="Asia/Seoul"
TRUST_POLICY="${REPO_DIR}/infra/iam/eventbridge-scheduler-trust-policy.json"
START_POLICY="${REPO_DIR}/infra/iam/eventbridge-start-ec2-policy.json"
TARGET_ARN="arn:aws:scheduler:::aws-sdk:ec2:startInstances"

print_permission_help() {
  cat >&2 <<EOF

ERROR: EventBridge Scheduler setup needs one-time IAM/Scheduler permissions.

Run this script from AWS CloudShell or an AWS CLI profile that can manage IAM
roles and EventBridge Scheduler resources. The EC2 batch role usually should
not have broad IAM role-creation permissions.

Required one-time permissions include:
  iam:GetRole
  iam:CreateRole
  iam:UpdateAssumeRolePolicy
  iam:PutRolePolicy
  iam:PassRole
  scheduler:GetSchedule
  scheduler:CreateSchedule
  scheduler:UpdateSchedule

After the schedule is created, the daily batch only needs the EC2 role's normal
pipeline permissions plus ec2:StopInstances for its own instance.
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
  cat >&2 <<EOF

If the error says "The execution role you provide must allow AWS EventBridge
Scheduler to assume the role", verify this trust policy on ${ROLE_NAME}:

aws iam get-role \\
  --role-name ${ROLE_NAME} \\
  --query 'Role.AssumeRolePolicyDocument' \\
  --output json

It must include:
  "Principal": { "Service": "scheduler.amazonaws.com" }
EOF
  exit 1
}

if [[ ! -f "${TRUST_POLICY}" ]]; then
  echo "Trust policy not found: ${TRUST_POLICY}" >&2
  exit 1
fi

if [[ ! -f "${START_POLICY}" ]]; then
  echo "Start policy not found: ${START_POLICY}" >&2
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
  --policy-document "file://${START_POLICY}"

ROLE_ARN="$(aws iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)" || {
  print_permission_help
  exit 1
}

echo "Scheduler role ARN: ${ROLE_ARN}"
echo "Waiting for IAM role/trust-policy propagation..."
sleep 20

TARGET_JSON="$(printf '{"Arn":"%s","RoleArn":"%s","Input":"{\\"InstanceIds\\":[\\"%s\\"]}"}' "${TARGET_ARN}" "${ROLE_ARN}" "${INSTANCE_ID}")"

echo "Creating or updating schedule ${SCHEDULE_NAME}..."
if aws scheduler get-schedule --name "${SCHEDULE_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  run_schedule_command aws scheduler update-schedule \
    --name "${SCHEDULE_NAME}" \
    --region "${REGION}" \
    --schedule-expression "${SCHEDULE_EXPRESSION}" \
    --schedule-expression-timezone "${SCHEDULE_TIMEZONE}" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "${TARGET_JSON}"
else
  run_schedule_command aws scheduler create-schedule \
    --name "${SCHEDULE_NAME}" \
    --region "${REGION}" \
    --schedule-expression "${SCHEDULE_EXPRESSION}" \
    --schedule-expression-timezone "${SCHEDULE_TIMEZONE}" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "${TARGET_JSON}"
fi

echo
echo "EventBridge Scheduler setup complete."
echo "Schedule: ${SCHEDULE_NAME}"
echo "Cron: ${SCHEDULE_EXPRESSION}"
echo "Timezone: ${SCHEDULE_TIMEZONE}"
echo "Target instance: ${INSTANCE_ID}"
echo
echo "Verify with:"
echo "  aws scheduler get-schedule --name ${SCHEDULE_NAME} --region ${REGION}"

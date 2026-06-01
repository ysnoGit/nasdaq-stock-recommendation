#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ec2-user/projects/nasdaq-stock-recommendation}"
REGION="ap-northeast-2"
INSTANCE_ID="i-07311259548e90438"
ROLE_NAME="NasdaqStartEC2SchedulerRole"
POLICY_NAME="StartNasdaqBatchEC2Policy"
SCHEDULE_NAME="start-nasdaq-batch-ec2-weekdays"
SCHEDULE_EXPRESSION="cron(0 8 ? * MON-FRI *)"
SCHEDULE_TIMEZONE="Asia/Seoul"
TRUST_POLICY="${REPO_DIR}/infra/iam/eventbridge-scheduler-trust-policy.json"
START_POLICY="${REPO_DIR}/infra/iam/eventbridge-start-ec2-policy.json"
TARGET_ARN="arn:aws:scheduler:::aws-sdk:ec2:startInstances"

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
  aws iam update-assume-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-document "file://${TRUST_POLICY}"
else
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${TRUST_POLICY}"
fi

aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "${POLICY_NAME}" \
  --policy-document "file://${START_POLICY}"

ROLE_ARN="$(aws iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text)"

TARGET_JSON="$(printf '{"Arn":"%s","RoleArn":"%s","Input":"{\\"InstanceIds\\":[\\"%s\\"]}"}' "${TARGET_ARN}" "${ROLE_ARN}" "${INSTANCE_ID}")"

echo "Creating or updating schedule ${SCHEDULE_NAME}..."
if aws scheduler get-schedule --name "${SCHEDULE_NAME}" --region "${REGION}" >/dev/null 2>&1; then
  aws scheduler update-schedule \
    --name "${SCHEDULE_NAME}" \
    --region "${REGION}" \
    --schedule-expression "${SCHEDULE_EXPRESSION}" \
    --schedule-expression-timezone "${SCHEDULE_TIMEZONE}" \
    --flexible-time-window '{"Mode":"OFF"}' \
    --target "${TARGET_JSON}"
else
  aws scheduler create-schedule \
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

#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ec2-user/projects/nasdaq-stock-recommendation}"
SERVICE_NAME="nasdaq-daily-batch.service"
SOURCE_SERVICE="${REPO_DIR}/infra/systemd/${SERVICE_NAME}"
TARGET_SERVICE="/etc/systemd/system/${SERVICE_NAME}"

if [[ ! -f "${SOURCE_SERVICE}" ]]; then
  echo "Service template not found: ${SOURCE_SERVICE}" >&2
  exit 1
fi

echo "Installing ${SERVICE_NAME}..."
sudo cp "${SOURCE_SERVICE}" "${TARGET_SERVICE}"
sudo systemctl daemon-reload
sudo systemctl disable "${SERVICE_NAME}" || true

echo
echo "Installed ${SERVICE_NAME}."
echo "This service is installed but not enabled on boot."
echo "Current enablement state:"
state="$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
echo "${state:-unknown}"
if [[ "${state}" == "static" || "${state}" == "disabled" ]]; then
  echo "${SERVICE_NAME} will not start automatically on boot."
fi
echo
echo "Test manually with:"
echo "  sudo systemctl start ${SERVICE_NAME}"
echo
echo "Check logs with:"
echo "  journalctl -u ${SERVICE_NAME} -n 100 --no-pager"
echo "  tail -100 ${REPO_DIR}/logs/daily_batch_*.log"

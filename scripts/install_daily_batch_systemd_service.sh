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
sudo systemctl enable "${SERVICE_NAME}"

echo
echo "Installed and enabled ${SERVICE_NAME}."
echo
echo "Test manually with:"
echo "  sudo systemctl start ${SERVICE_NAME}"
echo
echo "Check logs with:"
echo "  journalctl -u ${SERVICE_NAME} -n 100 --no-pager"
echo "  tail -100 ${REPO_DIR}/logs/daily_batch_*.log"

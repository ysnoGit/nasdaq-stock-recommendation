#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="nasdaq-daily-batch.service"

echo "Disabling boot auto-run for ${SERVICE_NAME}..."
sudo systemctl disable "${SERVICE_NAME}" || true
sudo systemctl daemon-reload

echo
echo "Service enablement state:"
state="$(systemctl is-enabled "${SERVICE_NAME}" 2>/dev/null || true)"
echo "${state:-unknown}"
if [[ "${state}" == "static" || "${state}" == "disabled" ]]; then
  echo "${SERVICE_NAME} will not start automatically on boot."
fi

echo
echo "Manual start command:"
echo "  sudo systemctl start ${SERVICE_NAME}"

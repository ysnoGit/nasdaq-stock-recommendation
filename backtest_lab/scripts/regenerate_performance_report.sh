#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ -d venv ]] && source venv/bin/activate

bash backtest_lab/scripts/export_performance_comparison.sh
python3 backtest_lab/reports/build_performance_report.py

REPORT_DIR="backtest_lab/reports"
DOCX_PATH="${REPORT_DIR}/backtest_performance_comparison_report.docx"
PDF_PATH="${REPORT_DIR}/backtest_performance_comparison_report.pdf"
rm -f "${PDF_PATH}"

OFFICE_BIN=""
if command -v libreoffice >/dev/null 2>&1; then
  OFFICE_BIN="$(command -v libreoffice)"
elif command -v soffice >/dev/null 2>&1; then
  OFFICE_BIN="$(command -v soffice)"
elif [[ -x /Applications/LibreOffice.app/Contents/MacOS/soffice ]]; then
  OFFICE_BIN="/Applications/LibreOffice.app/Contents/MacOS/soffice"
fi

if [[ -n "${OFFICE_BIN}" ]]; then
  "${OFFICE_BIN}" --headless --convert-to pdf --outdir "${REPORT_DIR}" "${DOCX_PATH}" >/dev/null
  echo "PDF: ${PDF_PATH}"
else
  echo "LibreOffice not found; DOCX generated, but PDF was not generated."
fi

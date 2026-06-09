from __future__ import annotations

import shutil

from backtest_lab.src.config import TMP_DIR


def cleanup_generated_outputs() -> None:
    if TMP_DIR.exists():
        print(f"Removing previous generated output: {TMP_DIR}")
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

from __future__ import annotations

import os
import stat
from pathlib import Path

import wrds


def _validate_pgpass(pgpass_path: Path) -> None:
    if not pgpass_path.exists():
        raise RuntimeError(
            "WRDS .pgpass file is missing. Expected file path: "
            f"{pgpass_path}"
        )

    mode = stat.S_IMODE(pgpass_path.stat().st_mode)
    if mode != 0o600:
        raise RuntimeError(
            f"WRDS .pgpass permission is unsafe: {oct(mode)}. "
            "Run: chmod 600 ~/.pgpass"
        )


def get_wrds_connection() -> wrds.Connection:
    """Open a WRDS connection using WRDS_USERNAME and the user's ~/.pgpass file."""
    wrds_username = os.environ.get("WRDS_USERNAME")
    if not wrds_username:
        raise RuntimeError(
            'WRDS_USERNAME is not set. Run:\n'
            'export WRDS_USERNAME="your_wrds_username"'
        )

    _validate_pgpass(Path.home() / ".pgpass")

    return wrds.Connection(wrds_username=wrds_username)

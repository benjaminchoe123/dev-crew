"""Per-run sandbox directories under runs/<run_id>/."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path


def new_run_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{secrets.token_hex(2)}"


def create_workspace(base: Path, run_id: str) -> Path:
    ws = base / run_id
    ws.mkdir(parents=True, exist_ok=True)
    return ws

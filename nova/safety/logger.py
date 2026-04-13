"""JSONL audit logger: every Nova action is recorded to data/logs/audit.jsonl."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nova.config import AUDIT_LOG_ENABLED, LOGS_DIR

_AUDIT_PATH = LOGS_DIR / "audit.jsonl"
_SESSION_PATH = LOGS_DIR / "session.jsonl"


def _write(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def audit(
    event: str,
    *,
    tool: str = "",
    action: str = "",
    risk_level: str = "SAFE",
    user_text: str = "",
    nova_text: str = "",
    result: str = "",
    blocked: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one audit record to data/logs/audit.jsonl."""
    if not AUDIT_LOG_ENABLED:
        return

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "event": event,
        "tool": tool,
        "action": action,
        "risk_level": risk_level,
        "blocked": blocked,
    }
    if user_text:
        record["user_text"] = user_text[:200]
    if nova_text:
        record["nova_text"] = nova_text[:200]
    if result:
        record["result"] = result[:200]
    if extra:
        record["extra"] = extra

    _write(_AUDIT_PATH, record)


def session_log(event: str, data: dict[str, Any] | None = None) -> None:
    """Write a session-level event (startup, shutdown, wake, verify, etc.)."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    if data:
        record.update(data)
    _write(_SESSION_PATH, record)

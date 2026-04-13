"""Pipeline timing utilities.

Decorators
----------
  @timed("stage_name")  — wrap an async function; logs elapsed ms to
                          data/logs/performance.jsonl on every call.

Usage
-----
    from nova.utils.timing import timed

    @timed("stt")
    async def transcribe(pcm):
        ...
"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from nova.config import LOGS_DIR

_PERF_LOG: Path = LOGS_DIR / "performance.jsonl"
F = TypeVar("F", bound=Callable[..., Any])


def _log_timing(stage: str, elapsed_ms: float) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "elapsed_ms": round(elapsed_ms, 2),
    }
    with _PERF_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def timed(stage: str) -> Callable[[F], F]:
    """Decorator: measure wall-clock time of an async function and log it."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return await fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                _log_timing(stage, elapsed_ms)

        return wrapper  # type: ignore[return-value]

    return decorator


class PipelineTimer:
    """Context-manager based timer for measuring named stages inline.

    Usage
    -----
        timer = PipelineTimer()
        with timer.stage("vad"):
            pcm = await vad.capture()
        with timer.stage("stt"):
            text = await stt.transcribe(pcm)
        timer.report()
    """

    def __init__(self) -> None:
        self._stages: dict[str, float] = {}
        self._current: str = ""
        self._start: float = 0.0

    def stage(self, name: str) -> "PipelineTimer":
        self._current = name
        return self

    def __enter__(self) -> "PipelineTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        elapsed_ms = (time.perf_counter() - self._start) * 1000
        self._stages[self._current] = elapsed_ms
        _log_timing(self._current, elapsed_ms)

    def report(self) -> None:
        total = sum(self._stages.values())
        print("[Timing] Pipeline breakdown:")
        for stage, ms in self._stages.items():
            bar = "█" * max(1, int(ms / 50))
            print(f"  {stage:20s} {ms:7.1f} ms  {bar}")
        print(f"  {'TOTAL':20s} {total:7.1f} ms")


def read_recent_timings(n: int = 50) -> list[dict[str, Any]]:
    """Return the last *n* timing entries from performance.jsonl."""
    if not _PERF_LOG.exists():
        return []
    lines = _PERF_LOG.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in reversed(lines[-n * 2:]):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
        if len(entries) >= n:
            break
    return list(reversed(entries))

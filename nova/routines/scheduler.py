"""Nova scheduled routines.

Scheduler
---------
Runs built-in and user-defined routines on a cron-like schedule using asyncio.
Routines are persisted to memory/preferences as JSON.

Built-in routines
-----------------
  morning_briefing  — daily at 09:00  — weather, calendar, unread emails, top news
  end_of_day        — daily at 18:00  — summarise today's actions, remind of tomorrow

Custom routines
---------------
Users define via voice: "every morning at 9, check my emails and tell me my schedule"
The scheduler parses simple natural-language schedules and stores them.

Mock mode
---------
  python -m nova.routines.scheduler --trigger morning_briefing
  (or pass --list to show all scheduled routines)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine

from nova.config import DATA_DIR, MOCK_MODE, ROUTINE_ENABLED

_PREFS_PATH: Path = DATA_DIR.parent / "nova" / "memory" / "routines.json"
_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Routine:
    name: str                    # unique identifier
    description: str             # human-readable
    schedule: str                # "daily@09:00", "hourly", "every 30m"
    prompt: str                  # text sent to the agent when triggered
    enabled: bool = True
    last_run: str = ""           # ISO timestamp

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Routine":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Built-in routines ─────────────────────────────────────────────────────────

_BUILTIN_ROUTINES: list[Routine] = [
    Routine(
        name="morning_briefing",
        description="Morning briefing: weather, calendar, unread emails, top news",
        schedule="daily@09:00",
        prompt=(
            "Give me my morning briefing: "
            "today's weather, my calendar for today, "
            "a summary of unread emails, and the top 3 news headlines."
        ),
    ),
    Routine(
        name="end_of_day",
        description="End of day: summarise actions taken, remind of tomorrow's events",
        schedule="daily@18:00",
        prompt=(
            "Give me an end-of-day summary: "
            "what did we accomplish today, and what's on my calendar for tomorrow?"
        ),
    ),
]


# ── Scheduler ─────────────────────────────────────────────────────────────────

class Scheduler:
    """Async scheduler.  Call start() to begin background scheduling."""

    def __init__(
        self,
        on_trigger: Callable[[Routine], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """on_trigger(routine) — async coroutine called when a routine fires."""
        self._on_trigger = on_trigger or self._default_trigger
        self._routines: list[Routine] = []
        self._task: asyncio.Task[None] | None = None
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load routines from disk, merging with built-ins."""
        saved: list[dict[str, Any]] = []
        if _PREFS_PATH.exists():
            try:
                saved = json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
            except Exception:
                saved = []

        saved_names = {r["name"] for r in saved}
        # Start with built-ins, then append any user-defined routines not in built-ins
        self._routines = list(_BUILTIN_ROUTINES)
        for d in saved:
            if d["name"] not in {r.name for r in _BUILTIN_ROUTINES}:
                self._routines.append(Routine.from_dict(d))
        # Apply saved state (enabled/last_run) to built-ins
        saved_map = {d["name"]: d for d in saved}
        for r in self._routines:
            if r.name in saved_map:
                r.enabled = saved_map[r.name].get("enabled", r.enabled)
                r.last_run = saved_map[r.name].get("last_run", "")

    def _save(self) -> None:
        _PREFS_PATH.write_text(
            json.dumps([r.to_dict() for r in self._routines], indent=2),
            encoding="utf-8",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def list_routines(self) -> list[Routine]:
        return list(self._routines)

    def add_routine(self, routine: Routine) -> None:
        self._routines = [r for r in self._routines if r.name != routine.name]
        self._routines.append(routine)
        self._save()

    def remove_routine(self, name: str) -> bool:
        before = len(self._routines)
        self._routines = [r for r in self._routines if r.name != name]
        self._save()
        return len(self._routines) < before

    def enable(self, name: str, enabled: bool = True) -> None:
        for r in self._routines:
            if r.name == name:
                r.enabled = enabled
                self._save()
                return

    async def trigger(self, name: str) -> bool:
        """Manually trigger a named routine.  Returns False if not found."""
        for r in self._routines:
            if r.name == name:
                await self._on_trigger(r)
                return True
        return False

    def start(self) -> asyncio.Task[None]:
        """Start the background scheduling loop."""
        if not ROUTINE_ENABLED:
            print("[Scheduler] Routines disabled (ROUTINE_ENABLED=false).")
        self._task = asyncio.create_task(self._loop(), name="nova-scheduler")
        return self._task

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    # ── Natural-language schedule parsing ────────────────────────────────────

    @staticmethod
    def parse_schedule(text: str) -> str | None:
        """Convert a natural-language description to a schedule string.

        Examples
        --------
          "every morning at 9"    → "daily@09:00"
          "every day at 6pm"      → "daily@18:00"
          "every hour"            → "hourly"
          "every 30 minutes"      → "every 30m"
        Returns None if unparseable.
        """
        text = text.lower().strip()

        # "every hour" / "hourly"
        if re.search(r"every\s+hour|hourly", text):
            return "hourly"

        # "every N minutes/hours"
        m = re.search(r"every\s+(\d+)\s+(min|minute|hour)", text)
        if m:
            n, unit = m.group(1), m.group(2)
            return f"every {n}{'h' if 'hour' in unit else 'm'}"

        # "every day at HH:MM" / "every morning at N" / "daily at Npm"
        m = re.search(
            r"(every\s+day|daily|every\s+morning|every\s+evening|every\s+night)"
            r".*?at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
            text,
        )
        if m:
            hour = int(m.group(2))
            minute = int(m.group(3) or 0)
            ampm = m.group(4)
            if ampm == "pm" and hour != 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            return f"daily@{hour:02d}:{minute:02d}"

        return None

    # ── Scheduling loop ───────────────────────────────────────────────────────

    async def _loop(self) -> None:
        print("[Scheduler] Started.")
        while True:
            now = datetime.now()
            for routine in self._routines:
                if not routine.enabled:
                    continue
                if self._should_run(routine, now):
                    routine.last_run = now.isoformat()
                    self._save()
                    print(f"[Scheduler] Triggering routine: {routine.name}")
                    try:
                        await self._on_trigger(routine)
                    except Exception as exc:
                        print(f"[Scheduler] Error in routine {routine.name}: {exc}")
            # Sleep until the start of the next minute
            await asyncio.sleep(60 - datetime.now().second)

    def _should_run(self, routine: Routine, now: datetime) -> bool:
        """Return True if the routine should fire right now (within this minute)."""
        sched = routine.schedule

        if sched == "hourly":
            # Fire at the top of every hour
            if now.minute != 0:
                return False

        elif sched.startswith("every "):
            # e.g. "every 30m" or "every 2h"
            m = re.match(r"every (\d+)(m|h)", sched)
            if not m:
                return False
            n, unit = int(m.group(1)), m.group(2)
            interval_minutes = n if unit == "m" else n * 60
            return now.minute % interval_minutes == 0

        elif sched.startswith("daily@"):
            # e.g. "daily@09:00"
            try:
                t_str = sched[len("daily@"):]
                h, mn = map(int, t_str.split(":"))
                if now.hour != h or now.minute != mn:
                    return False
            except ValueError:
                return False

        else:
            return False

        # Prevent double-firing within the same minute
        if routine.last_run:
            try:
                last = datetime.fromisoformat(routine.last_run)
                if (now - last) < timedelta(minutes=1):
                    return False
            except ValueError:
                pass

        return True

    # ── Default trigger (mock) ────────────────────────────────────────────────

    @staticmethod
    async def _default_trigger(routine: Routine) -> None:
        print(f"\n[Routine] {routine.name}: {routine.description}")
        print(f"  Prompt: {routine.prompt}\n")
        if MOCK_MODE:
            print(f"  [Mock] Would send to agent: '{routine.prompt}'\n")


# ── CLI for manual testing ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    scheduler = Scheduler()

    if "--list" in sys.argv:
        print("Scheduled routines:")
        for r in scheduler.list_routines():
            status = "enabled" if r.enabled else "disabled"
            print(f"  {r.name:25s} [{status:8s}] {r.schedule:15s} — {r.description}")
        sys.exit(0)

    if "--trigger" in sys.argv:
        idx = sys.argv.index("--trigger")
        name = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if not name:
            print("Usage: python -m nova.routines.scheduler --trigger <name>")
            sys.exit(1)
        result = asyncio.run(scheduler.trigger(name))
        if not result:
            print(f"Routine '{name}' not found.")
            sys.exit(1)
        sys.exit(0)

    print("Usage:")
    print("  python -m nova.routines.scheduler --list")
    print("  python -m nova.routines.scheduler --trigger morning_briefing")

"""SQLite + FTS5 memory store.

Tables
------
episodes    — conversation turns (user_text, nova_text, ts)
preferences — key/value owner settings
workflows   — saved multi-step task definitions
contacts    — people the owner mentions
fts_episodes — virtual FTS5 table mirroring episodes
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import aiosqlite

from nova.config import DATA_DIR

_DB_PATH = DATA_DIR / "nova_memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_text  TEXT NOT NULL,
    nova_text  TEXT NOT NULL,
    ts         REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS preferences (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS workflows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    steps       TEXT NOT NULL,   -- JSON array of step strings
    created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    notes      TEXT,
    updated_at REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_episodes USING fts5(
    user_text,
    nova_text,
    content='episodes',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO fts_episodes(rowid, user_text, nova_text)
    VALUES (new.id, new.user_text, new.nova_text);
END;

CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO fts_episodes(fts_episodes, rowid, user_text, nova_text)
    VALUES ('delete', old.id, old.user_text, old.nova_text);
END;
"""


class MemoryStore:
    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(str(self._db_path))
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        # Seed defaults on first run
        await self._seed_defaults()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _seed_defaults(self) -> None:
        from nova.memory.defaults import DEFAULT_PREFERENCES
        for key, value in DEFAULT_PREFERENCES.items():
            await self._conn.execute(  # type: ignore[union-attr]
                "INSERT OR IGNORE INTO preferences (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        await self._conn.commit()  # type: ignore[union-attr]

    # ── Episodes ──────────────────────────────────────────────────────────────

    async def add_episode(self, user_text: str, nova_text: str) -> int:
        assert self._conn is not None
        cur = await self._conn.execute(
            "INSERT INTO episodes (user_text, nova_text) VALUES (?, ?)",
            (user_text, nova_text),
        )
        await self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    async def search_episodes(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        assert self._conn is not None
        cur = await self._conn.execute(
            """SELECT e.id, e.user_text, e.nova_text, e.ts
               FROM fts_episodes f
               JOIN episodes e ON e.id = f.rowid
               WHERE fts_episodes MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        )
        rows = await cur.fetchall()
        return [
            {"id": r[0], "user_text": r[1], "nova_text": r[2], "ts": r[3]}
            for r in rows
        ]

    async def recent_episodes(self, limit: int = 5) -> list[dict[str, Any]]:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT id, user_text, nova_text, ts FROM episodes ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [
            {"id": r[0], "user_text": r[1], "nova_text": r[2], "ts": r[3]}
            for r in rows
        ]

    # ── Preferences ───────────────────────────────────────────────────────────

    async def get_preference(self, key: str) -> Any:
        assert self._conn is not None
        cur = await self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        return json.loads(row[0]) if row else None

    async def set_preference(self, key: str, value: Any) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, unixepoch('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value)),
        )
        await self._conn.commit()

    # ── Contacts ─────────────────────────────────────────────────────────────

    async def upsert_contact(self, name: str, notes: str) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO contacts (name, notes) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET notes=excluded.notes, updated_at=unixepoch('now') "
            "WHERE 1=1",
            (name, notes),
        )
        await self._conn.commit()

    # ── Workflows ─────────────────────────────────────────────────────────────

    async def save_workflow(self, name: str, description: str, steps: list[str]) -> None:
        assert self._conn is not None
        await self._conn.execute(
            "INSERT INTO workflows (name, description, steps) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description, steps=excluded.steps",
            (name, description, json.dumps(steps)),
        )
        await self._conn.commit()

    # ── Utility ───────────────────────────────────────────────────────────────

    async def count(self, table: str) -> int:
        assert self._conn is not None
        _allowed = {"episodes", "preferences", "workflows", "contacts"}
        if table not in _allowed:
            raise ValueError(f"Unknown table: {table}")
        cur = await self._conn.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def build_context_string(self, query: str) -> str:
        """Return a formatted string of relevant memories for system prompt injection."""
        episodes = await self.search_episodes(query, limit=5)
        if not episodes:
            episodes = await self.recent_episodes(limit=3)
        if not episodes:
            return ""
        lines = []
        for ep in episodes:
            lines.append(f"- User: {ep['user_text'][:120]}")
            lines.append(f"  Nova: {ep['nova_text'][:120]}")
        return "\n".join(lines)

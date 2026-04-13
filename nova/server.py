"""Nova FastAPI + WebSocket server.

REST endpoints
--------------
  GET  /health                  — liveness check
  GET  /status                  — runtime stats
  GET  /settings                — read current settings
  POST /settings                — update settings (subset of config vars)
  GET  /routines                — list scheduled routines
  POST /routines/{name}/trigger — manually trigger a routine
  PUT  /routines/{name}         — enable/disable a routine
  GET  /tts-cache/stats         — TTS cache statistics
  GET  /performance             — last 50 timing entries
  WS   /ws                      — bidirectional text command channel
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nova import __version__
from nova.config import (
    CLAP_ENABLED,
    CLAP_THRESHOLD,
    DATA_DIR,
    HOST,
    MOCK_MODE,
    PORT,
    PROACTIVE_SUGGESTIONS,
    ROUTINE_ENABLED,
    TTS_CACHE_ENABLED,
    TTS_CACHE_DIR,
    TTS_CACHE_MAX_SIZE,
    WAKE_METHODS,
)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Nova",
    description="Voice-gated personal desktop AI agent",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory connection registry ────────────────────────────────────────────
_connections: set[WebSocket] = set()


# ── REST endpoints ───────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "version": __version__,
            "mock_mode": MOCK_MODE,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/status")
async def status() -> JSONResponse:
    from nova.memory.store import MemoryStore

    store = MemoryStore()
    await store.init()
    episode_count = await store.count("episodes")
    return JSONResponse(
        {
            "connections": len(_connections),
            "episodes": episode_count,
            "mock_mode": MOCK_MODE,
        }
    )


@app.get("/settings")
async def get_settings() -> JSONResponse:
    """Return current runtime settings."""
    return JSONResponse(
        {
            "wake_methods": WAKE_METHODS,
            "clap_enabled": CLAP_ENABLED,
            "clap_threshold": CLAP_THRESHOLD,
            "routine_enabled": ROUTINE_ENABLED,
            "tts_cache_enabled": TTS_CACHE_ENABLED,
            "tts_cache_max_size": TTS_CACHE_MAX_SIZE,
            "proactive_suggestions": PROACTIVE_SUGGESTIONS,
            "mock_mode": MOCK_MODE,
        }
    )


@app.post("/settings")
async def update_settings(payload: dict[str, Any]) -> JSONResponse:
    """Write accepted settings back to .env (best-effort; takes effect on restart).

    Accepted keys: clap_enabled, clap_threshold, routine_enabled,
                   tts_cache_enabled, proactive_suggestions, wake_methods
    """
    _ENV_MAP: dict[str, str] = {
        "clap_enabled": "CLAP_ENABLED",
        "clap_threshold": "CLAP_THRESHOLD",
        "routine_enabled": "ROUTINE_ENABLED",
        "tts_cache_enabled": "TTS_CACHE_ENABLED",
        "proactive_suggestions": "PROACTIVE_SUGGESTIONS",
        "wake_methods": "WAKE_METHODS",
    }
    env_path = DATA_DIR.parent / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated: dict[str, Any] = {}
    for key, value in payload.items():
        env_key = _ENV_MAP.get(key)
        if not env_key:
            continue
        if isinstance(value, list):
            value = ",".join(str(v) for v in value)
        new_line = f"{env_key}={value}"
        replaced = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_key}="):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        updated[key] = value

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return JSONResponse({"updated": updated, "note": "Restart Nova to apply changes."})


# ── Routines endpoints ────────────────────────────────────────────────────────

@app.get("/routines")
async def list_routines() -> JSONResponse:
    from nova.routines.scheduler import Scheduler

    scheduler = Scheduler()
    return JSONResponse([r.to_dict() for r in scheduler.list_routines()])


@app.post("/routines/{name}/trigger")
async def trigger_routine(name: str) -> JSONResponse:
    from nova.routines.scheduler import Scheduler

    scheduler = Scheduler()
    ok = await scheduler.trigger(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Routine '{name}' not found.")
    return JSONResponse({"triggered": name})


@app.put("/routines/{name}")
async def update_routine(name: str, payload: dict[str, Any]) -> JSONResponse:
    from nova.routines.scheduler import Scheduler

    scheduler = Scheduler()
    enabled = payload.get("enabled")
    if enabled is None:
        raise HTTPException(status_code=400, detail="Provide 'enabled': true/false")
    scheduler.enable(name, bool(enabled))
    return JSONResponse({"name": name, "enabled": bool(enabled)})


# ── TTS cache stats ───────────────────────────────────────────────────────────

@app.get("/tts-cache/stats")
async def tts_cache_stats() -> JSONResponse:
    files = list(TTS_CACHE_DIR.glob("*.mp3"))
    total_bytes = sum(f.stat().st_size for f in files)
    return JSONResponse(
        {
            "entries": len(files),
            "max_size": TTS_CACHE_MAX_SIZE,
            "total_mb": round(total_bytes / 1_048_576, 2),
            "enabled": TTS_CACHE_ENABLED,
        }
    )


# ── Performance metrics ───────────────────────────────────────────────────────

@app.get("/performance")
async def performance_metrics() -> JSONResponse:
    from nova.utils.timing import read_recent_timings

    entries = read_recent_timings(50)
    # Aggregate by stage
    agg: dict[str, list[float]] = {}
    for e in entries:
        agg.setdefault(e["stage"], []).append(e["elapsed_ms"])
    summary = {
        stage: {
            "count": len(vals),
            "avg_ms": round(sum(vals) / len(vals), 1),
            "min_ms": round(min(vals), 1),
            "max_ms": round(max(vals), 1),
        }
        for stage, vals in agg.items()
    }
    return JSONResponse({"summary": summary, "recent": entries[-20:]})


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _connections.add(ws)
    try:
        await ws.send_json({"type": "connected", "mock_mode": MOCK_MODE})
        while True:
            raw = await ws.receive_text()
            try:
                msg: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "detail": "invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await ws.send_json({"type": "pong"})

            elif msg_type == "text_input":
                # Allow frontend to submit text commands directly (useful in mock mode)
                text = str(msg.get("text", "")).strip()
                if text:
                    asyncio.create_task(_handle_text(ws, text))

            else:
                await ws.send_json({"type": "error", "detail": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)


async def broadcast(payload: dict[str, Any]) -> None:
    """Push a message to all connected WebSocket clients."""
    dead: set[WebSocket] = set()
    for ws in _connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)


async def _handle_text(ws: WebSocket, text: str) -> None:
    """Process a text command from the WebSocket and stream the response."""
    from nova.brain.agents import AgentOrchestrator
    from nova.safety.guardrails import Guardrails
    from nova.memory.store import MemoryStore

    guardrails = Guardrails()
    if not guardrails.check_input(text):
        await ws.send_json({"type": "blocked", "detail": "input blocked by guardrails"})
        return

    await ws.send_json({"type": "thinking"})

    orchestrator = AgentOrchestrator()
    reply = await orchestrator.run(text)

    safe_reply = guardrails.redact_output(reply)

    store = MemoryStore()
    await store.init()
    await store.add_episode(user_text=text, nova_text=safe_reply)

    await ws.send_json({"type": "response", "text": safe_reply})


# ── Entry point ───────────────────────────────────────────────────────────────
def run_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    run_server()

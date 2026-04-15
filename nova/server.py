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

WebSocket /ws
-------------
  Client → Server message types:
    ping                         — keepalive (server replies "pong")
    text_input   {text}          — run text command through pipeline
    voice_input  {audio: b64}    — base64 WebM audio → STT → pipeline
    approval     {approved: bool}— user answer to approval_required prompt

  Server → Client message types:
    connected    {mock_mode}     — handshake on connect
    pong                         — ping reply
    state        {state}         — orb state: idle|listening|thinking|speaking|error
    thinking                     — agent is processing (also triggers state→thinking)
    transcribed  {text}          — STT result after voice_input
    response     {text, audio?}  — agent reply; audio is base64 MP3 when TTS succeeds
    approval_required {description, risk_level, prompt} — user must approve/deny
    blocked      {detail}        — guardrails or policy blocked the request
    error        {detail}        — unexpected server error
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
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
    SAFETY_CONFIRM_HIGH,
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

# Per-connection approval futures (keyed by id(ws))
_approval_futures: dict[int, "asyncio.Future[bool]"] = {}


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
                text = str(msg.get("text", "")).strip()
                if text:
                    asyncio.create_task(_handle_text(ws, text))

            elif msg_type == "voice_input":
                audio_b64 = str(msg.get("audio", ""))
                if audio_b64:
                    asyncio.create_task(_handle_voice(ws, audio_b64))

            elif msg_type == "approval":
                # Resolve a pending approval future for this connection
                fut = _approval_futures.get(id(ws))
                if fut and not fut.done():
                    fut.set_result(bool(msg.get("approved", False)))

            else:
                await ws.send_json({"type": "error", "detail": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(ws)
        # Cancel any pending approval for this connection
        fut = _approval_futures.pop(id(ws), None)
        if fut and not fut.done():
            fut.cancel()


# ── Broadcast helpers ─────────────────────────────────────────────────────────

async def broadcast(payload: dict[str, Any]) -> None:
    """Push a message to all connected WebSocket clients."""
    dead: set[WebSocket] = set()
    for ws in _connections:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)


async def broadcast_state(state: str) -> None:
    """Broadcast an orb state change to all connected clients."""
    await broadcast({"type": "state", "state": state})


# ── Approval flow ─────────────────────────────────────────────────────────────

async def _request_approval(ws: WebSocket, description: str, risk_level: str) -> bool:
    """Ask the connected client to approve a HIGH/CRITICAL action.

    Sends approval_required, waits up to 30 s for an 'approval' reply.
    Returns False on timeout or denial.
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[bool] = loop.create_future()
    _approval_futures[id(ws)] = fut
    try:
        await ws.send_json(
            {
                "type": "approval_required",
                "description": description,
                "risk_level": risk_level,
                "prompt": f"Allow {risk_level} action: {description}?",
            }
        )
        return await asyncio.wait_for(asyncio.shield(fut), timeout=30.0)
    except asyncio.TimeoutError:
        print(f"[Server] Approval timeout for: {description}")
        return False
    finally:
        _approval_futures.pop(id(ws), None)


# ── Voice input handler ───────────────────────────────────────────────────────

async def _handle_voice(ws: WebSocket, audio_b64: str) -> None:
    """Decode incoming base64 audio (WebM from browser), run STT, then pipeline."""
    from nova.speech.stt import STT

    await broadcast_state("listening")
    tmp_path: str | None = None
    try:
        raw = base64.b64decode(audio_b64)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(raw)
            tmp_path = tf.name

        stt = STT()
        text = await stt.transcribe_file(tmp_path)

        if text:
            await ws.send_json({"type": "transcribed", "text": text})
            await _handle_text(ws, text)
        else:
            await broadcast_state("idle")
    except Exception as exc:
        print(f"[Server] voice_input error: {exc}")
        await ws.send_json({"type": "error", "detail": "Voice transcription failed."})
        await broadcast_state("error")
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass


# ── Text pipeline handler ─────────────────────────────────────────────────────

async def _handle_text(ws: WebSocket, text: str) -> None:
    """Run text through guardrails → optional approval → agent → TTS → respond."""
    from nova.brain.agents import AgentOrchestrator
    from nova.safety.guardrails import Guardrails
    from nova.safety.governance import classify, RiskLevel
    from nova.memory.store import MemoryStore
    from nova.voice.tts import TTS

    guardrails = Guardrails()

    # ── Input guardrails ──────────────────────────────────────────────────────
    if not guardrails.check_input(text):
        await ws.send_json({"type": "blocked", "detail": "Input blocked by safety guardrails."})
        await broadcast_state("error")
        return

    # ── Pre-classify risk; ask for approval if HIGH/CRITICAL ─────────────────
    if SAFETY_CONFIRM_HIGH:
        assessment = classify("", "", context=text)
        if assessment.level == RiskLevel.BLOCKED:
            await ws.send_json(
                {"type": "blocked", "detail": f"Action blocked: {assessment.reason}"}
            )
            await broadcast_state("error")
            return
        if assessment.level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            approved = await _request_approval(ws, assessment.reason, assessment.level.name)
            if not approved:
                await ws.send_json(
                    {
                        "type": "blocked",
                        "detail": f"Action not approved ({assessment.level.name}: {assessment.reason})",
                    }
                )
                await broadcast_state("idle")
                return

    # ── Run agent ─────────────────────────────────────────────────────────────
    await broadcast_state("thinking")
    await ws.send_json({"type": "thinking"})

    try:
        orchestrator = AgentOrchestrator()
        reply = await orchestrator.run(text)
    except Exception as exc:
        print(f"[Server] Agent error: {exc}")
        await ws.send_json({"type": "error", "detail": "Agent encountered an error."})
        await broadcast_state("error")
        return

    safe_reply = guardrails.redact_output(reply)

    # ── Persist to memory ─────────────────────────────────────────────────────
    try:
        store = MemoryStore()
        await store.init()
        await store.add_episode(user_text=text, nova_text=safe_reply)
    except Exception as exc:
        print(f"[Server] Memory store error: {exc}")

    # ── Synthesise TTS audio ──────────────────────────────────────────────────
    audio_b64: str | None = None
    try:
        tts = TTS()
        audio_bytes = await tts._synthesise(safe_reply)
        if audio_bytes:
            audio_b64 = base64.b64encode(audio_bytes).decode()
    except Exception as exc:
        print(f"[Server] TTS synthesis failed: {exc}")

    # ── Send response ─────────────────────────────────────────────────────────
    await broadcast_state("speaking")
    payload: dict[str, Any] = {"type": "response", "text": safe_reply}
    if audio_b64:
        payload["audio"] = audio_b64
    await ws.send_json(payload)

    # If no audio was generated, explicitly return to idle here.
    # When audio IS included, the frontend's AudioPlayer handles the idle transition.
    if not audio_b64:
        await broadcast_state("idle")


# ── Entry point ───────────────────────────────────────────────────────────────
def run_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    run_server()

"""Nova v2 — main async event loop.

Pipeline
--------
wake word / clap → capture utterance → verify speaker → transcribe →
    agent orchestrator → proactive suggestion → TTS → log to memory

Usage
-----
    python -m nova.main               # mock mode (default from .env)
    python -m nova.main --server      # also start the FastAPI/WebSocket server
    python -m nova.main --no-tray     # disable system tray icon
"""

from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

# ── Bootstrap: ensure we're running from the repo root ───────────────────────
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from nova.config import MOCK_MODE, HOST, PORT, PROACTIVE_SUGGESTIONS
from nova.safety.killswitch import register as register_killswitch, unregister
from nova.safety.logger import session_log, audit
from nova.safety.guardrails import Guardrails
from nova.wake.wakeword import WakeWordDetector
from nova.wake.vad import VAD
from nova.wake.speaker_verify import SpeakerVerifier
from nova.speech.stt import STT
from nova.brain.agents import AgentOrchestrator
from nova.brain.proactive import ProactiveSuggestions
from nova.voice.tts import TTS
from nova.memory.store import MemoryStore
from nova.utils.timing import PipelineTimer

_SHUTDOWN = asyncio.Event()


def _print_banner() -> None:
    mode = "mock" if MOCK_MODE else "live"
    banner = (
        "\n  _   _  ___  __   __ _\n"
        " | \\ | |/ _ \\ \\ \\ / // \\\n"
        " |  \\| | | | | \\ V // _ \\\n"
        " | |\\  | |_| |  | |/ ___ \\\n"
        f" |_| \\_|\\___/   |_/_/   \\_\\   v2  [{mode} mode]\n"
    )
    print(banner)


# ── Pre-warm models ───────────────────────────────────────────────────────────

async def _prewarm(stt: STT, verifier: SpeakerVerifier) -> None:
    """Load Whisper and SpeechBrain models in the background at startup."""
    if MOCK_MODE:
        return
    loop = asyncio.get_event_loop()
    tasks = []
    if hasattr(stt, "prewarm"):
        tasks.append(loop.run_in_executor(None, stt.prewarm))
    if hasattr(verifier, "prewarm"):
        tasks.append(loop.run_in_executor(None, verifier.prewarm))
    if tasks:
        print("[Nova] Pre-warming models…")
        await asyncio.gather(*tasks, return_exceptions=True)
        print("[Nova] Models ready.")


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _run_pipeline(
    vad: VAD,
    verifier: SpeakerVerifier,
    stt: STT,
    orchestrator: AgentOrchestrator,
    tts: TTS,
    store: MemoryStore,
    guardrails: Guardrails,
    proactive: ProactiveSuggestions,
    wake_source: str,
) -> bool:
    """One wake→response cycle.  Returns False to signal shutdown."""
    timer = PipelineTimer()

    # ── 1. Capture utterance ─────────────────────────────────────────────────
    session_log("capture_start", {"wake_source": wake_source})
    with timer.stage("vad"):
        pcm = await vad.capture()

    # ── 2. Speaker verification ──────────────────────────────────────────────
    session_log("verify_start")
    with timer.stage("speaker_verify"):
        verified = await verifier.verify(pcm)
    if not verified:
        print("[Nova] Speaker not recognised — ignoring.")
        session_log("verify_failed")
        await tts.speak("Sorry, I don't recognise that voice.")
        return True
    session_log("verify_ok")

    # ── 3. Transcribe ────────────────────────────────────────────────────────
    session_log("stt_start")
    with timer.stage("stt"):
        user_text = await stt.transcribe(pcm)
    if not user_text.strip():
        print("[Nova] No speech detected.")
        return True

    print(f"\n[You] {user_text}")
    audit("stt", user_text=user_text)

    if user_text.strip().lower() in ("quit", "exit", "goodbye nova", "shut down"):
        await tts.speak("Goodbye!")
        return False

    # ── 4. Guardrails (input) ─────────────────────────────────────────────────
    if not guardrails.check_input(user_text):
        await tts.speak("I can't help with that request.")
        audit("guardrail_block", user_text=user_text, blocked=True)
        return True

    # ── 5. Agent orchestrator ─────────────────────────────────────────────────
    session_log("agent_start")
    with timer.stage("agent"):
        memory_context = await store.build_context_string(user_text)
        nova_text = await orchestrator.run(user_text, memory_context=memory_context)

    # ── 6. Guardrails (output) ────────────────────────────────────────────────
    nova_text = guardrails.redact_output(nova_text)
    print(f"[Nova] {nova_text}\n")
    audit("response", user_text=user_text, nova_text=nova_text)

    # ── 7. TTS ────────────────────────────────────────────────────────────────
    with timer.stage("tts"):
        await tts.speak(nova_text)

    # ── 8. Proactive suggestion ───────────────────────────────────────────────
    if PROACTIVE_SUGGESTIONS:
        suggestion = proactive.suggest(nova_text)
        if suggestion:
            await tts.speak(suggestion)
            session_log("proactive_suggestion", {"suggestion": suggestion})

    # ── 9. Log to memory ─────────────────────────────────────────────────────
    await store.add_episode(user_text=user_text, nova_text=nova_text)
    session_log("episode_saved")

    if not MOCK_MODE:
        timer.report()

    return True


# ── Main entry ────────────────────────────────────────────────────────────────

async def run(start_server: bool = False, enable_tray: bool = True) -> None:
    _print_banner()
    print(f"[Nova] Starting {'in mock mode' if MOCK_MODE else 'in live mode'}…")
    print("[Nova] Press Ctrl+C or Ctrl+Shift+K to exit.\n")

    # ── Init components ───────────────────────────────────────────────────────
    store = MemoryStore()
    await store.init()

    vad = VAD()
    verifier = SpeakerVerifier()
    stt = STT()
    orchestrator = AgentOrchestrator()
    tts = TTS()
    guardrails = Guardrails()
    proactive = ProactiveSuggestions()

    # ── Pre-warm models ───────────────────────────────────────────────────────
    await _prewarm(stt, verifier)

    # ── System tray ───────────────────────────────────────────────────────────
    tray = None
    if enable_tray:
        try:
            from nova.ui.tray import TrayIcon

            def _quit_cb() -> None:
                _SHUTDOWN.set()

            tray = TrayIcon(on_quit=_quit_cb)
            tray.start()
        except Exception as exc:
            print(f"[Nova] Tray icon unavailable: {exc}")

    # ── Scheduler ─────────────────────────────────────────────────────────────
    from nova.routines.scheduler import Scheduler

    async def _on_routine(routine) -> None:
        nova_text = await orchestrator.run(routine.prompt)
        nova_text = guardrails.redact_output(nova_text)
        print(f"[Routine:{routine.name}] {nova_text}")
        await tts.speak(nova_text)

    scheduler = Scheduler(on_trigger=_on_routine)
    scheduler.start()

    # ── Kill switch ───────────────────────────────────────────────────────────
    def _on_kill() -> None:
        _SHUTDOWN.set()

    register_killswitch(callback=_on_kill)

    # ── OS signal handlers ────────────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _SHUTDOWN.set)
        except (NotImplementedError, OSError):
            pass

    # ── Optional API server ───────────────────────────────────────────────────
    if start_server:
        import uvicorn
        from nova.server import app
        server_cfg = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
        server = uvicorn.Server(server_cfg)
        asyncio.create_task(server.serve())
        print(f"[Nova] WebSocket server listening on ws://{HOST}:{PORT}/ws\n")

    session_log("startup", {"mock_mode": MOCK_MODE})

    # ── Main event loop ───────────────────────────────────────────────────────
    if MOCK_MODE:
        from nova.config import WAKE_METHODS
        methods_hint = "Enter=voice"
        if "clap" in WAKE_METHODS:
            methods_hint += ", s+Enter=clap"
        print(f"[Nova] Mock mode: {methods_hint}, 'quit'=exit.\n")

    if tray:
        tray.set_state("idle")

    async with WakeWordDetector() as detector:
        async for wake_source in detector.listen():
            if _SHUTDOWN.is_set():
                break

            print(f"\n[Nova] Wake trigger ({wake_source}) — listening…")
            session_log("wake", {"source": wake_source})

            if tray:
                tray.set_state("listening")

            try:
                should_continue = await _run_pipeline(
                    vad, verifier, stt, orchestrator,
                    tts, store, guardrails, proactive,
                    wake_source,
                )
            except Exception as exc:
                print(f"[Nova] Pipeline error: {exc}")
                session_log("pipeline_error", {"error": str(exc)})
                if tray:
                    tray.set_state("error")
                should_continue = True
            else:
                if tray:
                    tray.set_state("idle")

            if not should_continue or _SHUTDOWN.is_set():
                break

    session_log("shutdown")
    scheduler.stop()
    if tray:
        tray.stop()
    unregister()
    await store.close()
    print("\n[Nova] Goodbye.")


def cli_entry() -> None:
    """Entry point for `nova` console script and `python -m nova.main`."""
    start_server = "--server" in sys.argv
    no_tray = "--no-tray" in sys.argv
    asyncio.run(run(start_server=start_server, enable_tray=not no_tray))


if __name__ == "__main__":
    cli_entry()

"""Wake-word detection: Porcupine "Hey Nova" and/or double-clap.

Wake methods are controlled by WAKE_METHODS in config:
  - "voice"  → Porcupine keyword engine (or Enter key in mock mode)
  - "clap"   → ClapDetector double-clap (or Spacebar / 's' in mock mode)

Either trigger fires the wake event; both run concurrently when enabled.

Mock mode
---------
  Enter       → voice wake
  's' + Enter → clap wake
  'quit'      → exit
"""

from __future__ import annotations

import asyncio
import struct
import threading
from typing import AsyncIterator

from nova.config import (
    CLAP_ENABLED,
    MOCK_MODE,
    PORCUPINE_ACCESS_KEY,
    WAKE_METHODS,
    WAKEWORDS_DIR,
)


class WakeWordDetector:
    """Async context manager that yields (source, ) whenever any wake trigger fires.

    source is "voice" or "clap".
    """

    def __init__(self) -> None:
        self._porcupine = None
        self._audio_stream = None
        self._wake_queue: asyncio.Queue[str] = asyncio.Queue()

    async def __aenter__(self) -> "WakeWordDetector":
        if not MOCK_MODE and "voice" in WAKE_METHODS:
            await asyncio.get_event_loop().run_in_executor(None, self._init_porcupine)
        return self

    async def __aexit__(self, *_: object) -> None:
        self._cleanup()

    # ── Porcupine setup ───────────────────────────────────────────────────────

    def _init_porcupine(self) -> None:
        import pvporcupine  # type: ignore[import]

        ppn_files = list(WAKEWORDS_DIR.glob("*.ppn"))
        if ppn_files:
            self._porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keyword_paths=[str(ppn_files[0])],
            )
        else:
            self._porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY,
                keywords=["hey siri"],  # closest built-in; replace with custom .ppn for "Hey Nova"
            )

        import pyaudio  # type: ignore[import]

        pa = pyaudio.PyAudio()
        self._audio_stream = pa.open(
            rate=self._porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self._porcupine.frame_length,
        )

    def _cleanup(self) -> None:
        if self._audio_stream:
            try:
                self._audio_stream.close()
            except Exception:
                pass
        if self._porcupine:
            try:
                self._porcupine.delete()
            except Exception:
                pass

    # ── Public listen interface ───────────────────────────────────────────────

    async def listen(self) -> AsyncIterator[str]:
        """Async generator — yields the trigger source ("voice" or "clap")."""
        if MOCK_MODE:
            async for source in self._mock_listen():
                yield source
        else:
            async for source in self._real_listen():
                yield source

    # ── Mock mode ─────────────────────────────────────────────────────────────

    async def _mock_listen(self) -> AsyncIterator[str]:
        methods = ", ".join(WAKE_METHODS) if WAKE_METHODS else "voice"
        print(
            f"[WakeWord] Mock mode (methods: {methods})\n"
            "  Enter   → voice wake\n"
            "  s+Enter → clap wake\n"
            "  quit    → exit\n"
        )
        loop = asyncio.get_event_loop()
        while True:
            line: str = await loop.run_in_executor(None, input, "")
            stripped = line.strip().lower()
            if stripped in ("quit", "exit", "q"):
                return
            if stripped in ("s", "space", "clap") and "clap" in WAKE_METHODS:
                print("[WakeWord] Clap wake simulated.")
                yield "clap"
            elif "voice" in WAKE_METHODS:
                print("[WakeWord] Voice wake simulated.")
                yield "voice"
            # If neither method is enabled, silently loop

    # ── Real mode ─────────────────────────────────────────────────────────────

    async def _real_listen(self) -> AsyncIterator[str]:
        """Run enabled detectors in background threads; yield from shared queue."""
        loop = asyncio.get_event_loop()

        if "voice" in WAKE_METHODS and self._porcupine:
            threading.Thread(
                target=self._porcupine_thread,
                args=(loop,),
                daemon=True,
                name="nova-porcupine",
            ).start()

        if "clap" in WAKE_METHODS and CLAP_ENABLED:
            threading.Thread(
                target=self._clap_thread,
                args=(loop,),
                daemon=True,
                name="nova-clap",
            ).start()

        while True:
            source: str = await self._wake_queue.get()
            yield source

    def _porcupine_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        frame_length: int = self._porcupine.frame_length
        try:
            while True:
                pcm_bytes = self._audio_stream.read(frame_length)
                pcm = struct.unpack_from(f"{frame_length}h", pcm_bytes)
                if self._porcupine.process(pcm) >= 0:
                    print("[WakeWord] Hey Nova detected!")
                    loop.call_soon_threadsafe(self._wake_queue.put_nowait, "voice")
        except Exception as exc:
            print(f"[WakeWord] Porcupine thread error: {exc}")

    def _clap_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        from nova.wake.clap_detector import ClapDetector

        detector = ClapDetector()
        try:
            import pyaudio  # type: ignore[import]

            pa = pyaudio.PyAudio()
            stream = pa.open(
                rate=detector.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=320,  # 20 ms @ 16 kHz
            )
            print("[ClapDetector] Listening for double-clap…")
            while True:
                frame = stream.read(320, exception_on_overflow=False)
                if detector.process_frame(frame):
                    print("[ClapDetector] Double-clap detected!")
                    loop.call_soon_threadsafe(self._wake_queue.put_nowait, "clap")
        except Exception as exc:
            print(f"[WakeWord] Clap thread error: {exc}")

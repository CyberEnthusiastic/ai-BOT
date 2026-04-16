"""Wake-word detection.

Engine selection — WAKEWORD_ENGINE in config:
  "whisper"       — FREE, listens for any custom phrase via Whisper STT (default)
                    Set WAKEWORD_PHRASE=hey nova (or any phrase you want)
                    No training needed — works immediately!
  "openwakeword"  — free, offline, built-in models only (hey_jarvis, alexa, etc.)
  "porcupine"     — Picovoice Porcupine (requires PORCUPINE_ACCESS_KEY)

Wake methods — controlled by WAKE_METHODS in config:
  "voice"  — keyword engine (whisper/openwakeword/porcupine)
  "clap"   — double-clap detector

Mock mode:
  Enter       — voice wake
  s + Enter   — clap wake
  quit        — exit
"""

from __future__ import annotations

import asyncio
import struct
import threading
from typing import AsyncIterator

from nova.config import (
    AUDIO_INPUT_DEVICE,
    CLAP_ENABLED,
    MOCK_MODE,
    OPENWAKEWORD_MODEL,
    PORCUPINE_ACCESS_KEY,
    WAKE_METHODS,
    WAKEWORD_ENGINE,
    WAKEWORD_PHRASE,
    WAKEWORDS_DIR,
)

# Audio constants for openwakeword (16 kHz, mono, int16, 80 ms chunks)
_OWW_SAMPLE_RATE = 16_000
_OWW_CHUNK_MS    = 80
_OWW_CHUNK_SIZE  = _OWW_SAMPLE_RATE * _OWW_CHUNK_MS // 1000  # 1 280 samples


class WakeWordDetector:
    """Async context manager — yields the trigger source ("voice" | "clap")."""

    def __init__(self) -> None:
        self._oww_model   = None   # openwakeword Model
        self._porcupine   = None   # pvporcupine handle
        self._audio_stream = None  # shared pyaudio stream (Porcupine path)
        self._wake_queue: asyncio.Queue[str] = asyncio.Queue()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def __aenter__(self) -> "WakeWordDetector":
        if not MOCK_MODE and "voice" in WAKE_METHODS:
            loop = asyncio.get_event_loop()
            if WAKEWORD_ENGINE == "porcupine":
                await loop.run_in_executor(None, self._init_porcupine)
            elif WAKEWORD_ENGINE == "openwakeword":
                await loop.run_in_executor(None, self._init_openwakeword)
            # "whisper" engine needs no init — loads model on first detection
        return self

    async def __aexit__(self, *_: object) -> None:
        self._cleanup()

    # ── openwakeword init ─────────────────────────────────────────────────────

    def _init_openwakeword(self) -> None:
        try:
            from openwakeword.model import Model  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "openwakeword not installed. Run: pip install openwakeword"
            ) from exc

        # openwakeword downloads model weights on first use; subsequent runs are cached.
        self._oww_model = Model(
            wakeword_models=[OPENWAKEWORD_MODEL],
            inference_framework="onnx",  # fastest, no torch required
        )
        print(f"[WakeWord] openwakeword ready — listening for '{OPENWAKEWORD_MODEL}'")

    # ── Porcupine init (optional premium path) ────────────────────────────────

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
                keywords=["hey siri"],  # closest built-in; swap for custom .ppn
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
        print("[WakeWord] Porcupine ready")

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

    # ── Public API ────────────────────────────────────────────────────────────

    async def listen(self) -> AsyncIterator[str]:
        """Async generator — yields "voice" or "clap" on each wake event."""
        if MOCK_MODE:
            async for source in self._mock_listen():
                yield source
        else:
            async for source in self._real_listen():
                yield source

    # ── Mock mode ─────────────────────────────────────────────────────────────

    async def _mock_listen(self) -> AsyncIterator[str]:
        methods = ", ".join(WAKE_METHODS) if WAKE_METHODS else "voice"
        engine  = WAKEWORD_ENGINE if not MOCK_MODE else "mock"
        print(
            f"[WakeWord] Mock mode (engine: {engine}, methods: {methods})\n"
            "  Enter   -> voice wake\n"
            "  s+Enter -> clap wake\n"
            "  quit    -> exit\n"
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

    # ── Real mode ─────────────────────────────────────────────────────────────

    async def _real_listen(self) -> AsyncIterator[str]:
        """Spin up detector threads; yield from shared queue."""
        loop = asyncio.get_event_loop()

        if "voice" in WAKE_METHODS:
            if WAKEWORD_ENGINE == "whisper":
                threading.Thread(
                    target=self._whisper_thread,
                    args=(loop,),
                    daemon=True,
                    name="nova-whisper-wake",
                ).start()
            elif WAKEWORD_ENGINE == "porcupine" and self._porcupine:
                threading.Thread(
                    target=self._porcupine_thread,
                    args=(loop,),
                    daemon=True,
                    name="nova-porcupine",
                ).start()
            elif self._oww_model:
                threading.Thread(
                    target=self._oww_thread,
                    args=(loop,),
                    daemon=True,
                    name="nova-oww",
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

    # ── openwakeword background thread ────────────────────────────────────────

    def _oww_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        """Continuously feed mic audio to openwakeword and fire on detection."""
        try:
            import pyaudio  # type: ignore[import]
            import numpy as np  # type: ignore[import]
        except ImportError as exc:
            print(f"[WakeWord] openwakeword thread error — missing dep: {exc}")
            return

        pa     = pyaudio.PyAudio()
        stream = pa.open(
            rate=_OWW_SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=_OWW_CHUNK_SIZE,
        )

        # openwakeword expects a float32 numpy array OR raw int16 bytes depending on version
        # We pass raw bytes; the library normalises internally.
        print(f"[WakeWord] openwakeword listening for '{OPENWAKEWORD_MODEL}'…")
        try:
            while True:
                audio_chunk = stream.read(_OWW_CHUNK_SIZE, exception_on_overflow=False)
                # Convert int16 bytes → float32 numpy array in [-1, 1]
                pcm_int16 = np.frombuffer(audio_chunk, dtype=np.int16)
                pcm_float = pcm_int16.astype(np.float32) / 32768.0

                prediction = self._oww_model.predict(pcm_float)
                # prediction is {model_name: score, ...}; score > 0.5 == detected
                for model_name, score in prediction.items():
                    if score > 0.5:
                        print(f"[WakeWord] '{model_name}' detected (score={score:.2f})!")
                        loop.call_soon_threadsafe(self._wake_queue.put_nowait, "voice")
                        # Brief cooldown — model resets scores internally
                        import time; time.sleep(2.0)
                        break
        except Exception as exc:
            print(f"[WakeWord] openwakeword thread error: {exc}")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    # ── Whisper keyword thread ────────────────────────────────────────────────

    def _whisper_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        """Listen for WAKEWORD_PHRASE using Whisper STT on 2-second chunks.

        No training needed — works with any phrase you set in WAKEWORD_PHRASE.
        Slightly more CPU than openwakeword but fully custom and free.
        """
        try:
            import pyaudio  # type: ignore[import]
            import numpy as np  # type: ignore[import]
            from faster_whisper import WhisperModel  # type: ignore[import]
            from nova.config import MODELS_DIR
        except ImportError as exc:
            print(f"[WakeWord] Whisper thread — missing dep: {exc}")
            return

        # Load tiny model for fast wake-word inference
        model = WhisperModel(
            "tiny.en",
            device="cpu",
            compute_type="int8",
            download_root=str(MODELS_DIR / "whisper"),
        )

        phrase = WAKEWORD_PHRASE.lower().strip()

        pa = pyaudio.PyAudio()
        if AUDIO_INPUT_DEVICE >= 0:
            dev_info = pa.get_device_info_by_index(AUDIO_INPUT_DEVICE)
        else:
            dev_info = pa.get_default_input_device_info()
        native_rate = int(dev_info["defaultSampleRate"])
        native_channels = min(int(dev_info["maxInputChannels"]), 2)

        target_rate   = 16_000
        chunk_seconds = 2
        chunk_size    = native_rate * chunk_seconds

        print(f"[WakeWord] Whisper engine ready — say '{phrase}' to wake Nova "
              f"(device={AUDIO_INPUT_DEVICE}, rate={native_rate}Hz, ch={native_channels})")

        open_kwargs: dict = dict(
            rate=native_rate,
            channels=native_channels,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=1024,
        )
        if AUDIO_INPUT_DEVICE >= 0:
            open_kwargs["input_device_index"] = AUDIO_INPUT_DEVICE
        stream = pa.open(**open_kwargs)

        import time
        cooldown_until = 0.0

        try:
            while True:
                frames = []
                samples_collected = 0
                while samples_collected < chunk_size:
                    data = stream.read(1024, exception_on_overflow=False)
                    frames.append(data)
                    samples_collected += 1024

                if time.time() < cooldown_until:
                    continue

                raw = b"".join(frames)
                pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                if native_channels > 1:
                    pcm = pcm.reshape(-1, native_channels).mean(axis=1)

                if native_rate != target_rate:
                    target_len = int(len(pcm) * target_rate / native_rate)
                    pcm = np.interp(
                        np.linspace(0, len(pcm), target_len, endpoint=False),
                        np.arange(len(pcm)),
                        pcm,
                    ).astype(np.float32)

                # Auto-gain: boost quiet mics so Whisper can transcribe
                peak = float(np.abs(pcm).max())
                if 0.01 < peak < 0.3:
                    pcm = np.clip(pcm * (0.5 / peak), -1.0, 1.0).astype(np.float32)

                segments, _ = model.transcribe(
                    pcm,
                    language="en",
                    beam_size=1,
                    vad_filter=True,
                )
                transcript = " ".join(s.text.strip() for s in segments).lower()

                if transcript and phrase in transcript:
                    print(f"[WakeWord] '{phrase}' detected! (heard: '{transcript.strip()}')")
                    loop.call_soon_threadsafe(self._wake_queue.put_nowait, "voice")
                    cooldown_until = time.time() + 3.0  # 3s cooldown

        except Exception as exc:
            print(f"[WakeWord] Whisper thread error: {exc}")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    # ── Porcupine background thread ───────────────────────────────────────────

    def _porcupine_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        frame_length: int = self._porcupine.frame_length
        try:
            while True:
                pcm_bytes = self._audio_stream.read(frame_length)
                pcm = struct.unpack_from(f"{frame_length}h", pcm_bytes)
                if self._porcupine.process(pcm) >= 0:
                    print("[WakeWord] Hey Nova detected (Porcupine)!")
                    loop.call_soon_threadsafe(self._wake_queue.put_nowait, "voice")
        except Exception as exc:
            print(f"[WakeWord] Porcupine thread error: {exc}")

    # ── Clap background thread ────────────────────────────────────────────────

    def _clap_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        from nova.wake.clap_detector import ClapDetector

        detector = ClapDetector()
        try:
            import pyaudio  # type: ignore[import]

            pa     = pyaudio.PyAudio()
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

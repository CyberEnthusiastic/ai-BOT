"""Voice Activity Detection: Silero VAD to capture a complete utterance.

Mock mode returns a fixed-duration silence-padded buffer.
"""

from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path

import numpy as np

from nova.config import MOCK_MODE, RECORDINGS_DIR

# VAD tuning
_SAMPLE_RATE = 16_000
_CHUNK_MS = 30          # ms per analysis frame
_SILENCE_TIMEOUT = 1.2  # seconds of silence to end utterance
_MAX_DURATION = 30.0    # hard cap in seconds
_MOCK_DURATION = 2.0    # fake recording duration in mock mode


class VAD:
    """Captures audio from the microphone until the speaker stops talking."""

    def __init__(self) -> None:
        self._model = None

    def _load_model(self) -> None:
        import torch  # type: ignore[import]

        model, utils = torch.hub.load(  # type: ignore[attr-defined]
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
        self._model = model
        self._get_speech_timestamps = utils[0]

    async def capture(self) -> bytes:
        """Record until VAD detects end-of-utterance.  Returns raw PCM bytes (16-bit mono 16 kHz)."""
        if MOCK_MODE:
            return await self._mock_capture()
        return await asyncio.get_event_loop().run_in_executor(None, self._real_capture)

    async def _mock_capture(self) -> bytes:
        """Return silence-like PCM of fixed duration (simulates a recorded utterance)."""
        print(f"[VAD] Mock: simulating {_MOCK_DURATION}s utterance capture.")
        await asyncio.sleep(0.1)  # tiny yield so the loop stays responsive
        num_samples = int(_SAMPLE_RATE * _MOCK_DURATION)
        # Very-low-amplitude noise so downstream models see something non-zero
        rng = np.random.default_rng(seed=42)
        pcm = (rng.uniform(-100, 100, num_samples)).astype(np.int16)
        return pcm.tobytes()

    def _real_capture(self) -> bytes:
        import pyaudio  # type: ignore[import]
        import torch  # type: ignore[import]

        if self._model is None:
            self._load_model()

        pa = pyaudio.PyAudio()
        chunk_size = int(_SAMPLE_RATE * _CHUNK_MS / 1000)
        stream = pa.open(
            rate=_SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=chunk_size,
        )

        frames: list[bytes] = []
        silence_start: float | None = None
        start = time.monotonic()

        print("[VAD] Listening…")
        try:
            while True:
                raw = stream.read(chunk_size, exception_on_overflow=False)
                frames.append(raw)
                audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                tensor = torch.from_numpy(audio_np)
                speech_prob = float(self._model(tensor, _SAMPLE_RATE).item())

                elapsed = time.monotonic() - start
                if elapsed > _MAX_DURATION:
                    break

                if speech_prob < 0.5:
                    if silence_start is None:
                        silence_start = time.monotonic()
                    elif time.monotonic() - silence_start > _SILENCE_TIMEOUT:
                        break
                else:
                    silence_start = None
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

        pcm_bytes = b"".join(frames)

        # Optionally save recording for debugging
        ts = int(time.time())
        out_path = RECORDINGS_DIR / f"utterance_{ts}.wav"
        _save_wav(out_path, pcm_bytes, _SAMPLE_RATE)

        return pcm_bytes


def _save_wav(path: Path, pcm: bytes, sample_rate: int) -> None:
    import wave

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)

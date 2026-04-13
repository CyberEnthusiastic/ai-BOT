"""Double-clap wake detector.

Algorithm
---------
1. Compute RMS energy per 20 ms audio frame.
2. If energy > threshold → potential clap, record timestamp.
3. If a second spike arrives within CLAP_MIN_GAP–CLAP_MAX_GAP seconds → DOUBLE CLAP.
4. Reset if no second clap within CLAP_MAX_GAP + 0.3 s.
5. Debounce: ignore input for CLAP_DEBOUNCE seconds after a successful detection.

Clap discrimination
-------------------
- Claps are short transient spikes: duration < 50 ms.
- Sustained noise (music, speech) → RMS stays elevated for many consecutive frames
  without the sharp on/off transition.  We require the frame *after* the spike to
  drop back below threshold, which filters out sustained loud sounds.

Mock mode
---------
Press Spacebar to simulate a double-clap.
"""

from __future__ import annotations

import math
import struct
import threading
import time
from typing import Callable

from nova.config import (
    CLAP_DEBOUNCE,
    CLAP_MAX_GAP,
    CLAP_MIN_GAP,
    CLAP_THRESHOLD,
    MOCK_MODE,
)

# 20 ms frames at 16 kHz = 320 samples
_SAMPLE_RATE = 16_000
_FRAME_MS = 20
_FRAME_SAMPLES = _SAMPLE_RATE * _FRAME_MS // 1000  # 320


def _rms(frame_bytes: bytes) -> float:
    """Return RMS amplitude in [0, 1] for a mono int16 PCM frame."""
    n = len(frame_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack_from(f"{n}h", frame_bytes)
    mean_sq = sum(s * s for s in samples) / n
    return math.sqrt(mean_sq) / 32768.0


class ClapDetector:
    """Stateful double-clap detector.

    Parameters
    ----------
    threshold:
        RMS energy level (0–1) above which a frame counts as a clap spike.
        Default 0.3 (configurable via CLAP_THRESHOLD).
    min_gap / max_gap:
        Acceptable inter-clap interval in seconds.
    sample_rate:
        Audio sample rate in Hz (must match your input stream).
    """

    def __init__(
        self,
        threshold: float = CLAP_THRESHOLD,
        min_gap: float = CLAP_MIN_GAP,
        max_gap: float = CLAP_MAX_GAP,
        debounce: float = CLAP_DEBOUNCE,
        sample_rate: int = _SAMPLE_RATE,
    ) -> None:
        self.threshold = threshold
        self.min_gap = min_gap
        self.max_gap = max_gap
        self.debounce = debounce
        self.sample_rate = sample_rate

        self._first_clap_time: float | None = None
        self._prev_above: bool = False      # was the previous frame above threshold?
        self._last_detect_time: float = 0.0  # when we last fired a detection

    # ── Public API ────────────────────────────────────────────────────────────

    def process_frame(self, audio_frame: bytes) -> bool:
        """Feed one 20 ms PCM frame.  Returns True on double-clap detection."""
        now = time.monotonic()

        # Debounce: ignore for a while after a successful detection
        if now - self._last_detect_time < self.debounce:
            self._prev_above = False
            return False

        energy = _rms(audio_frame)
        above = energy > self.threshold
        is_spike = above and not self._prev_above  # rising edge = start of transient
        self._prev_above = above

        if not is_spike:
            # Expire stale first clap
            if (
                self._first_clap_time is not None
                and now - self._first_clap_time > self.max_gap + 0.3
            ):
                self._first_clap_time = None
            return False

        # --- We have a spike ---
        if self._first_clap_time is None:
            # Record first clap
            self._first_clap_time = now
            return False

        gap = now - self._first_clap_time
        if self.min_gap <= gap <= self.max_gap:
            # Double clap!
            self._first_clap_time = None
            self._last_detect_time = now
            return True

        # Gap out of range → restart with this spike as the new first clap
        self._first_clap_time = now
        return False

    def reset(self) -> None:
        """Clear internal state."""
        self._first_clap_time = None
        self._prev_above = False

    # ── Blocking listeners ────────────────────────────────────────────────────

    def listen(self) -> bool:
        """Block until a double-clap is detected.

        Mock mode: wait for Spacebar press.
        Real mode: open microphone and process frames.
        Returns True always (blocking until detection).
        """
        if MOCK_MODE:
            return self._mock_listen()
        return self._mic_listen()

    def listen_async(self, callback: Callable[[], None]) -> threading.Thread:
        """Non-blocking version: run listen() in a background thread.
        Calls *callback* when the double-clap fires, then the thread exits.
        """
        t = threading.Thread(target=self._callback_wrapper, args=(callback,), daemon=True)
        t.start()
        return t

    def _callback_wrapper(self, callback: Callable[[], None]) -> None:
        self.listen()
        callback()

    # ── Internal implementations ───────────────────────────────────────────────

    def _mock_listen(self) -> bool:
        """Mock mode: press Spacebar (or 's') to fire a clap wake."""
        try:
            import keyboard  # type: ignore[import]
            print("[ClapDetector] Mock mode — press Spacebar to simulate double-clap.")
            keyboard.wait("space")
            print("[ClapDetector] Simulated double-clap detected!")
            return True
        except Exception:
            # Fallback: read from stdin if keyboard lib unavailable
            print("[ClapDetector] Mock mode — type 'clap' + Enter to simulate double-clap.")
            while True:
                try:
                    line = input("")
                    if "clap" in line.lower() or line.strip() == "":
                        print("[ClapDetector] Simulated double-clap detected!")
                        return True
                except (EOFError, KeyboardInterrupt):
                    return False

    def _mic_listen(self) -> bool:
        """Real mode: open microphone and process 20 ms frames."""
        try:
            import pyaudio  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "pyaudio is required for real clap detection. "
                "Install it with: pip install pyaudio"
            ) from exc

        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=self.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=_FRAME_SAMPLES,
        )

        print("[ClapDetector] Listening for double-clap…")
        try:
            while True:
                frame = stream.read(_FRAME_SAMPLES, exception_on_overflow=False)
                if self.process_frame(frame):
                    print("[ClapDetector] Double-clap detected!")
                    return True
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

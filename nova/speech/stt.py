"""Speech-to-text: faster-whisper (real) or keyboard input (mock)."""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

from nova.config import MOCK_MODE, MODELS_DIR

_MODEL_SIZE = "base.en"  # Swap to "small.en" or "medium.en" for better accuracy


class STT:
    """Transcribes raw PCM audio to text."""

    def __init__(self) -> None:
        self._model = None

    def _load(self) -> None:
        from faster_whisper import WhisperModel  # type: ignore[import]

        self._model = WhisperModel(
            _MODEL_SIZE,
            device="cpu",
            compute_type="int8",
            download_root=str(MODELS_DIR / "whisper"),
        )

    async def transcribe(self, pcm_bytes: bytes) -> str:
        """Transcribe audio. Returns empty string on failure."""
        if MOCK_MODE:
            return await self._mock_transcribe()
        return await asyncio.get_event_loop().run_in_executor(
            None, self._real_transcribe, pcm_bytes
        )

    async def _mock_transcribe(self) -> str:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, input, "[STT] Type your command: ")
        return text.strip()

    def _real_transcribe(self, pcm_bytes: bytes) -> str:
        import numpy as np  # type: ignore[import]
        import wave

        if self._model is None:
            self._load()

        # Write PCM to a temporary WAV file for faster-whisper
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16_000)
                wf.writeframes(pcm_bytes)

        try:
            segments, _info = self._model.transcribe(  # type: ignore[attr-defined]
                str(tmp_path),
                beam_size=5,
                language="en",
                vad_filter=True,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

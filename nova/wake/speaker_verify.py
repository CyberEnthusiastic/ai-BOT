"""Speaker verification: SpeechBrain ECAPA-TDNN cosine similarity.

Compares live audio against the enrolled owner voiceprint.
Mock mode always returns True (verified).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from nova.config import MOCK_MODE, MODELS_DIR, VOICEPRINTS_DIR, SPEAKER_THRESHOLD

_OWNER_PRINT_PATH = VOICEPRINTS_DIR / "owner.npy"
_SAMPLE_RATE = 16_000


class SpeakerVerifier:
    def __init__(self) -> None:
        self._classifier = None
        self._owner_embedding: np.ndarray | None = None

    def _load(self) -> None:
        from speechbrain.pretrained import SpeakerRecognition  # type: ignore[import]

        self._classifier = SpeakerRecognition.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(MODELS_DIR / "spkrec-ecapa"),
        )
        if _OWNER_PRINT_PATH.exists():
            self._owner_embedding = np.load(_OWNER_PRINT_PATH)

    async def verify(self, pcm_bytes: bytes) -> bool:
        """Return True if the speaker matches the enrolled owner."""
        if MOCK_MODE:
            return True

        if not _OWNER_PRINT_PATH.exists():
            # No voiceprint enrolled — fail open with a warning
            print("[SpeakerVerify] Warning: no voiceprint found, skipping verification.")
            return True

        result = await asyncio.get_event_loop().run_in_executor(
            None, self._verify_sync, pcm_bytes
        )
        return result

    def _verify_sync(self, pcm_bytes: bytes) -> bool:
        import torch  # type: ignore[import]

        if self._classifier is None:
            self._load()

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio).unsqueeze(0)  # (1, T)

        embedding = (
            self._classifier.encode_batch(tensor)  # type: ignore[attr-defined]
            .squeeze()
            .detach()
            .numpy()
        )

        if self._owner_embedding is None:
            return True  # No reference — let through

        similarity = float(_cosine_similarity(embedding, self._owner_embedding))
        print(f"[SpeakerVerify] cosine similarity = {similarity:.4f} (threshold {SPEAKER_THRESHOLD})")
        return similarity >= SPEAKER_THRESHOLD

    def extract_embedding(self, pcm_bytes: bytes) -> np.ndarray:
        """Extract a speaker embedding from raw PCM.  Used during enrollment."""
        import torch  # type: ignore[import]

        if self._classifier is None:
            self._load()

        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio).unsqueeze(0)
        return (
            self._classifier.encode_batch(tensor)  # type: ignore[attr-defined]
            .squeeze()
            .detach()
            .numpy()
        )


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)

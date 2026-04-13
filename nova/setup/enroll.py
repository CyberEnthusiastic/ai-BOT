"""Voice enrollment wizard.

Records 10 spoken phrases, extracts ECAPA-TDNN embeddings,
averages them, and saves the result to data/voiceprints/owner.npy.

Usage:
    python -m nova.setup.enroll
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

from nova.config import VOICEPRINTS_DIR, MOCK_MODE

_OWNER_PRINT_PATH = VOICEPRINTS_DIR / "owner.npy"

_ENROLLMENT_PHRASES = [
    "Hey Nova, open my documents folder.",
    "Search the web for today's news.",
    "Take a screenshot of the screen.",
    "Create a new text file on the desktop.",
    "What time is it right now?",
    "Open the calculator application.",
    "Show me the running processes.",
    "Read the contents of my latest file.",
    "Remind me to check my emails later.",
    "Nova, what can you help me with today?",
]


async def enroll() -> None:
    print("═" * 60)
    print("  Nova Voice Enrollment Wizard")
    print("═" * 60)
    print(f"\nYou will be prompted to say {len(_ENROLLMENT_PHRASES)} phrases.")
    print("Speak clearly, at a normal pace, 30–50 cm from the microphone.\n")

    if MOCK_MODE:
        print("[Enroll] MOCK_MODE=true — generating a random voiceprint for testing.\n")
        rng = np.random.default_rng(seed=0)
        embedding = rng.standard_normal(192).astype(np.float32)
        embedding /= np.linalg.norm(embedding)
        _OWNER_PRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.save(str(_OWNER_PRINT_PATH), embedding)
        print(f"[Enroll] Saved mock voiceprint to {_OWNER_PRINT_PATH}")
        return

    from nova.wake.vad import VAD
    from nova.wake.speaker_verify import SpeakerVerifier

    vad = VAD()
    verifier = SpeakerVerifier()
    embeddings: list[np.ndarray] = []

    for i, phrase in enumerate(_ENROLLMENT_PHRASES, start=1):
        print(f"[{i}/{len(_ENROLLMENT_PHRASES)}] Please say:\n  \"{phrase}\"\n")
        input("  Press Enter when ready, then speak…")

        pcm = await vad.capture()
        embedding = verifier.extract_embedding(pcm)
        embeddings.append(embedding)
        print(f"  ✓ Captured phrase {i}\n")

    if not embeddings:
        print("[Enroll] No phrases captured. Aborting.")
        return

    avg = np.mean(embeddings, axis=0)
    avg /= np.linalg.norm(avg)  # L2-normalise

    _OWNER_PRINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(_OWNER_PRINT_PATH), avg)

    print("═" * 60)
    print(f"  Enrollment complete! Voiceprint saved to:\n  {_OWNER_PRINT_PATH}")
    print("  You can now run Nova with MOCK_MODE=false.")
    print("═" * 60)


def main() -> None:
    asyncio.run(enroll())


if __name__ == "__main__":
    main()

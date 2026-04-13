"""Liveness check: random 3-word challenge to prevent replay attacks.

The user must repeat the displayed words; STT output is matched against them.
Mock mode skips the audio challenge and always returns True.
"""

from __future__ import annotations

import random
from pathlib import Path

from nova.config import MOCK_MODE

# Simple vocabulary for challenges — uncommon enough to avoid accidental match
_WORDS = [
    "apple", "river", "castle", "monkey", "lantern", "crystal", "dolphin",
    "thunder", "marble", "falcon", "window", "rocket", "garden", "pillow",
    "forest", "candle", "silver", "bridge", "mirror", "planet", "anchor",
    "blanket", "cactus", "dagger", "engine", "feather", "goblin", "harbor",
    "iceberg", "jungle", "kettle", "lizard", "magnet", "nectar", "oyster",
]

_CHALLENGE_LEN = 3


def generate_challenge() -> list[str]:
    """Return a list of N random words to display to the user."""
    return random.sample(_WORDS, _CHALLENGE_LEN)


def verify_response(challenge: list[str], stt_transcript: str) -> bool:
    """Check that the STT transcript contains all challenge words (case-insensitive).

    A lenient check: words just need to appear somewhere in the transcript,
    allowing for natural speech patterns like "I said apple river castle".
    """
    lower = stt_transcript.lower()
    return all(word in lower for word in challenge)


class LivenessChecker:
    """Orchestrates the challenge–response anti-replay flow."""

    async def run(self, stt_func) -> bool:  # type: ignore[type-arg]
        """Display a challenge, capture audio via stt_func, verify.

        stt_func: async callable that takes raw PCM bytes and returns a transcript string.
        In mock mode the user just types the words.
        """
        challenge = generate_challenge()
        phrase = " ".join(challenge)
        print(f"[Liveness] Please say: \"{phrase}\"")

        if MOCK_MODE:
            response = input("[Liveness] Type the challenge words: ").strip()
            return verify_response(challenge, response)

        # Real mode: capture a short utterance for liveness
        from nova.wake.vad import VAD
        vad = VAD()
        pcm = await vad.capture()
        transcript = await stt_func(pcm)
        passed = verify_response(challenge, transcript)
        if not passed:
            print(f"[Liveness] FAILED — heard: \"{transcript}\"")
        return passed

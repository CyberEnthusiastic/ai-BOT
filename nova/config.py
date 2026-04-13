"""Nova configuration — loads .env and exposes typed settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR: Path = Path(__file__).parent.parent
DATA_DIR: Path = ROOT_DIR / "data"

VOICEPRINTS_DIR: Path = DATA_DIR / "voiceprints"
WAKEWORDS_DIR: Path = DATA_DIR / "wakewords"
MODELS_DIR: Path = DATA_DIR / "models"
SCREENSHOTS_DIR: Path = DATA_DIR / "screenshots"
LOGS_DIR: Path = DATA_DIR / "logs"
RECORDINGS_DIR: Path = DATA_DIR / "recordings"
TTS_CACHE_DIR: Path = DATA_DIR / "tts_cache"

# Ensure data dirs exist at import time (non-gitignored subdirs are fine to create)
for _d in (
    VOICEPRINTS_DIR,
    WAKEWORDS_DIR,
    MODELS_DIR,
    SCREENSHOTS_DIR,
    LOGS_DIR,
    RECORDINGS_DIR,
    TTS_CACHE_DIR,
):
    _d.mkdir(parents=True, exist_ok=True)

# ── Load .env ─────────────────────────────────────────────────────────────────
load_dotenv(ROOT_DIR / ".env")


def _bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


# ── Global ────────────────────────────────────────────────────────────────────
MOCK_MODE: bool = _bool("MOCK_MODE", "true")
NOVA_OWNER_NAME: str = os.getenv("NOVA_OWNER_NAME", "User")

# ── OpenAI ───────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── ElevenLabs ───────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# ── Porcupine ────────────────────────────────────────────────────────────────
PORCUPINE_ACCESS_KEY: str = os.getenv("PORCUPINE_ACCESS_KEY", "")

# ── Speaker verification ─────────────────────────────────────────────────────
SPEAKER_THRESHOLD: float = _float("SPEAKER_THRESHOLD", 0.65)

# ── Server ───────────────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = _int("PORT", 8765)

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
AUDIT_LOG_ENABLED: bool = _bool("AUDIT_LOG_ENABLED", "true")

# ── Safety ───────────────────────────────────────────────────────────────────
SAFETY_BLOCK_CRITICAL: bool = _bool("SAFETY_BLOCK_CRITICAL", "true")
SAFETY_CONFIRM_HIGH: bool = _bool("SAFETY_CONFIRM_HIGH", "true")

# ── Wake detection ────────────────────────────────────────────────────────────
# WAKE_METHODS: comma-separated list of enabled wake triggers
# Valid values: "voice" (Porcupine), "clap" (double-clap detector)
WAKE_METHODS: list[str] = [
    m.strip()
    for m in os.getenv("WAKE_METHODS", "voice,clap").split(",")
    if m.strip()
]
CLAP_ENABLED: bool = _bool("CLAP_ENABLED", "true")
CLAP_THRESHOLD: float = _float("CLAP_THRESHOLD", 0.3)
CLAP_MIN_GAP: float = _float("CLAP_MIN_GAP", 0.3)   # seconds between claps (min)
CLAP_MAX_GAP: float = _float("CLAP_MAX_GAP", 0.7)   # seconds between claps (max)
CLAP_DEBOUNCE: float = _float("CLAP_DEBOUNCE", 2.0)  # silence after successful detect

# ── Scheduled routines ────────────────────────────────────────────────────────
ROUTINE_ENABLED: bool = _bool("ROUTINE_ENABLED", "true")

# ── TTS cache ────────────────────────────────────────────────────────────────
TTS_CACHE_ENABLED: bool = _bool("TTS_CACHE_ENABLED", "true")
TTS_CACHE_MAX_SIZE: int = _int("TTS_CACHE_MAX_SIZE", 100)  # max number of entries

# ── Proactive suggestions ────────────────────────────────────────────────────
PROACTIVE_SUGGESTIONS: bool = _bool("PROACTIVE_SUGGESTIONS", "true")

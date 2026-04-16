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
MOCK_MODE: bool = _bool("MOCK_MODE", "false")   # default live — free engines need no API keys
NOVA_OWNER_NAME: str = os.getenv("NOVA_OWNER_NAME", "User")

# ── OpenAI (optional — only needed if LLM_PROVIDER=openai) ──────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

# ── Anthropic / Claude (used when LLM_PROVIDER=claude) ───────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── Ollama (used when LLM_PROVIDER=ollama — free, runs locally) ───────────────
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ── LLM Provider ─────────────────────────────────────────────────────────────
# "ollama"  — free, local, no API key (default)
# "claude"  — Anthropic Claude (requires ANTHROPIC_API_KEY)
# "openai"  — OpenAI GPT (requires OPENAI_API_KEY)
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")

# ── ElevenLabs (optional premium TTS — falls back to edge-tts if absent) ─────
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

# ── Wake-word engine ──────────────────────────────────────────────────────────
# "openwakeword" — free, offline, no API key (default)
# "porcupine"    — Picovoice Porcupine (requires PORCUPINE_ACCESS_KEY)
WAKEWORD_ENGINE: str = os.getenv("WAKEWORD_ENGINE", "whisper")
OPENWAKEWORD_MODEL: str = os.getenv("OPENWAKEWORD_MODEL", "hey_jarvis")
# Custom wake phrase for WAKEWORD_ENGINE=whisper (any phrase you want!)
WAKEWORD_PHRASE: str = os.getenv("WAKEWORD_PHRASE", "hey nova")
# Mic device index — run: python -c "import pyaudio; ..." to list devices
# -1 = system default
AUDIO_INPUT_DEVICE: int = int(os.getenv("AUDIO_INPUT_DEVICE", "-1"))
# ^ Built-in models shipped with openwakeword.  Train a custom "hey_nova" model
#   and set OPENWAKEWORD_MODEL=hey_nova to use it.

# ── Porcupine (optional — only used when WAKEWORD_ENGINE=porcupine) ───────────
PORCUPINE_ACCESS_KEY: str = os.getenv("PORCUPINE_ACCESS_KEY", "")

# ── TTS engine ────────────────────────────────────────────────────────────────
# "edge"       — Microsoft Edge TTS via edge-tts (free, no key) ← default
# "elevenlabs" — ElevenLabs (requires ELEVENLABS_API_KEY)
# "openai"     — OpenAI TTS-1 (requires OPENAI_API_KEY)
# "pyttsx3"    — Windows/Mac offline TTS, no internet
TTS_ENGINE: str = os.getenv("TTS_ENGINE", "edge")
EDGE_TTS_VOICE: str = os.getenv("EDGE_TTS_VOICE", "en-GB-SoniaNeural")

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


# ── Convenience accessor ──────────────────────────────────────────────────────

def get_config() -> dict:
    """Return all current config values as a plain dict.

    Useful for health checks, settings API, and test introspection.
    """
    return {
        "mock_mode": MOCK_MODE,
        "nova_owner_name": NOVA_OWNER_NAME,
        "openai_model": OPENAI_MODEL,
        # TTS
        "tts_engine": TTS_ENGINE,
        "edge_tts_voice": EDGE_TTS_VOICE,
        "elevenlabs_voice_id": ELEVENLABS_VOICE_ID,
        # Wake word
        "wakeword_engine": WAKEWORD_ENGINE,
        "openwakeword_model": OPENWAKEWORD_MODEL,
        "wake_methods": WAKE_METHODS,
        # Clap
        "clap_enabled": CLAP_ENABLED,
        "clap_threshold": CLAP_THRESHOLD,
        "clap_min_gap": CLAP_MIN_GAP,
        "clap_max_gap": CLAP_MAX_GAP,
        "clap_debounce": CLAP_DEBOUNCE,
        # Speaker
        "speaker_threshold": SPEAKER_THRESHOLD,
        # Server
        "host": HOST,
        "port": PORT,
        # Logging / safety
        "log_level": LOG_LEVEL,
        "audit_log_enabled": AUDIT_LOG_ENABLED,
        "safety_block_critical": SAFETY_BLOCK_CRITICAL,
        "safety_confirm_high": SAFETY_CONFIRM_HIGH,
        # Routines / TTS cache / proactive
        "routine_enabled": ROUTINE_ENABLED,
        "tts_cache_enabled": TTS_CACHE_ENABLED,
        "tts_cache_max_size": TTS_CACHE_MAX_SIZE,
        "proactive_suggestions": PROACTIVE_SUGGESTIONS,
    }

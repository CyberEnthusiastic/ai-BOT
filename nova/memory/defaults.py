"""Default owner preferences seeded into memory on first run."""

from __future__ import annotations

from nova.config import NOVA_OWNER_NAME

DEFAULT_PREFERENCES: dict[str, object] = {
    # Identity
    "owner_name": NOVA_OWNER_NAME,
    "nova_version": "2.0.0",
    # Interaction style
    "response_verbosity": "concise",        # "concise" | "detailed"
    "confirm_high_risk": True,              # Prompt before HIGH risk actions
    "confirm_critical": True,              # Always prompt before CRITICAL actions
    # Privacy
    "save_recordings": False,              # Keep audio clips after transcription
    "share_analytics": False,              # No telemetry
    # Voice
    "tts_enabled": True,
    "tts_speed": 1.0,
    "tts_provider": "auto",               # "elevenlabs" | "openai" | "sapi" | "auto"
    # Wake word
    "wake_word": "Hey Nova",
    "liveness_check": False,              # Enable anti-replay challenge
    # Browser
    "browser_headless": False,
    "browser_engine": "chromium",
    # Notifications
    "desktop_notifications": True,
}

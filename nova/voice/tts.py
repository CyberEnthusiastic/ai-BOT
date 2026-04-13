"""Text-to-speech: ElevenLabs → OpenAI TTS → Windows SAPI → mock print.

Falls back through the chain until one provider succeeds.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

from nova.config import (
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    MOCK_MODE,
    OPENAI_API_KEY,
    TTS_CACHE_DIR,
)

_AUDIO_FORMAT = "mp3"


class TTS:
    """Multi-provider TTS with local caching."""

    async def speak(self, text: str) -> None:
        """Synthesise *text* and play it through the system speakers."""
        if MOCK_MODE:
            print(f"\n[Nova] {text}\n")
            return

        cache_path = self._cache_path(text)
        if not cache_path.exists():
            audio_bytes = await self._synthesise(text)
            if audio_bytes:
                cache_path.write_bytes(audio_bytes)

        if cache_path.exists():
            await self._play(cache_path)
        else:
            # All providers failed — fall back to SAPI
            await self._sapi_speak(text)

    # ── Synthesis chain ───────────────────────────────────────────────────────

    async def _synthesise(self, text: str) -> bytes | None:
        # 1. ElevenLabs
        if ELEVENLABS_API_KEY:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._elevenlabs_sync, text
            )
            if result:
                return result

        # 2. OpenAI TTS
        if OPENAI_API_KEY:
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._openai_tts_sync, text
            )
            if result:
                return result

        return None

    def _elevenlabs_sync(self, text: str) -> bytes | None:
        try:
            from elevenlabs import ElevenLabs  # type: ignore[import]

            client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
            audio_generator = client.text_to_speech.convert(
                voice_id=ELEVENLABS_VOICE_ID,
                text=text,
                model_id="eleven_turbo_v2",
                output_format="mp3_44100_128",
            )
            return b"".join(audio_generator)
        except Exception as exc:
            print(f"[TTS] ElevenLabs failed: {exc}")
            return None

    def _openai_tts_sync(self, text: str) -> bytes | None:
        try:
            from openai import OpenAI  # type: ignore[import]

            client = OpenAI(api_key=OPENAI_API_KEY)
            response = client.audio.speech.create(
                model="tts-1",
                voice="nova",
                input=text,
                response_format="mp3",
            )
            return response.read()
        except Exception as exc:
            print(f"[TTS] OpenAI TTS failed: {exc}")
            return None

    # ── Playback ──────────────────────────────────────────────────────────────

    async def _play(self, path: Path) -> None:
        """Play an mp3/wav file via Windows Media Player or afplay on Mac."""
        if sys.platform == "win32":
            cmd = ["powershell", "-c", f"(New-Object Media.SoundPlayer '{path}').PlaySync()"]
            # SoundPlayer only handles WAV; for mp3 use wmplayer
            cmd = ["powershell", "-c", f"$p=[System.Media.SoundPlayer]::new(); "
                   f"Add-Type -AssemblyName presentationCore; "
                   f"$m=[System.Windows.Media.MediaPlayer]::new(); "
                   f"$m.Open([uri]'{path.as_uri()}'); $m.Play(); Start-Sleep 10"]
            # Simpler cross-version approach: vlc / ffplay if available, else SAPI
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"$m = New-Object System.Windows.Media.MediaPlayer; "
                f"Add-Type -AssemblyName PresentationCore; "
                f"$m.Open([System.Uri]::new('{path.as_uri()}')); "
                f"$m.Play(); Start-Sleep -Milliseconds 10000",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        else:
            proc = await asyncio.create_subprocess_exec(
                "afplay", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()

    async def _sapi_speak(self, text: str) -> None:
        """Windows SAPI speech synthesis (no internet needed)."""
        if sys.platform != "win32":
            print(f"[Nova] {text}")
            return
        safe_text = text.replace('"', "'").replace("'", "\\'")
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f"Add-Type -AssemblyName System.speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak(\"{safe_text}\")",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    # ── Cache ─────────────────────────────────────────────────────────────────

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        return TTS_CACHE_DIR / f"{digest}.{_AUDIO_FORMAT}"

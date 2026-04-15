"""Text-to-speech — provider chain, newest-free-first.

Provider chain (tries each in order until one succeeds)
--------------------------------------------------------
1. edge-tts        — Microsoft Edge TTS via edge-tts package (FREE, no API key)
                     pip install edge-tts
                     Voice default: en-GB-SoniaNeural (natural British female)
2. ElevenLabs      — premium quality (requires ELEVENLABS_API_KEY)
3. OpenAI TTS-1    — good quality   (requires OPENAI_API_KEY)
4. pyttsx3         — Windows/Mac offline synthesis, no internet needed
5. mock print      — MOCK_MODE or all else fails

Audio caching (Phase 4)
-----------------------
Synthesised mp3 files are cached by SHA-256(text+voice) in data/tts_cache/.
Repeated phrases ("Done", "Opening Chrome") are served instantly from cache.
Cache is bounded by TTS_CACHE_MAX_SIZE (default 100 entries).

Playback
--------
Windows: PowerShell + PresentationCore MediaPlayer
macOS:   afplay
Linux:   ffplay (if installed) → pyttsx3

Configuration
-------------
TTS_ENGINE=edge          # primary engine preference
EDGE_TTS_VOICE=en-GB-SoniaNeural
ELEVENLABS_API_KEY=...   # optional premium upgrade
OPENAI_API_KEY=...       # used by brain AND tts-1 fallback
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path

from nova.config import (
    EDGE_TTS_VOICE,
    ELEVENLABS_API_KEY,
    ELEVENLABS_VOICE_ID,
    MOCK_MODE,
    OPENAI_API_KEY,
    TTS_CACHE_DIR,
    TTS_CACHE_ENABLED,
    TTS_CACHE_MAX_SIZE,
    TTS_ENGINE,
)

_AUDIO_FORMAT = "mp3"


class TTS:
    """Multi-provider TTS with local LRU caching."""

    # ── Public entry point ────────────────────────────────────────────────────

    async def speak(self, text: str) -> None:
        """Synthesise *text* and play it through the system speakers."""
        if MOCK_MODE:
            print(f"\n[Nova] {text}\n")
            return

        cache_path = self._cache_path(text)

        if TTS_CACHE_ENABLED and cache_path.exists():
            await self._play(cache_path)
            return

        audio_bytes = await self._synthesise(text)
        if audio_bytes:
            if TTS_CACHE_ENABLED:
                self._evict_if_needed()
                cache_path.write_bytes(audio_bytes)
            # Write to a temp file if caching is off so we can still play it
            target = cache_path if TTS_CACHE_ENABLED else self._temp_path(text)
            target.write_bytes(audio_bytes)
            await self._play(target)
            if not TTS_CACHE_ENABLED:
                try:
                    target.unlink()
                except Exception:
                    pass
        else:
            # Last resort: offline pyttsx3 / Windows SAPI
            await self._pyttsx3_speak(text)

    # ── Synthesis chain ───────────────────────────────────────────────────────

    async def _synthesise(self, text: str) -> bytes | None:
        # Ordered by preference; honour TTS_ENGINE to put user's choice first.
        providers = _build_provider_order(TTS_ENGINE)

        for provider in providers:
            result = await provider(self, text)
            if result:
                return result

        return None

    # ── Provider implementations ──────────────────────────────────────────────

    async def _edge_tts(self, text: str) -> bytes | None:
        """Microsoft Edge TTS — free, high quality, no API key."""
        try:
            import edge_tts  # type: ignore[import]
        except ImportError:
            print("[TTS] edge-tts not installed (pip install edge-tts)")
            return None

        try:
            # edge-tts writes to a file; we read back the bytes.
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                tmp = Path(tf.name)

            communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE)
            await communicate.save(str(tmp))
            data = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            return data
        except Exception as exc:
            print(f"[TTS] edge-tts failed: {exc}")
            return None

    async def _elevenlabs(self, text: str) -> bytes | None:
        """ElevenLabs — premium optional."""
        if not ELEVENLABS_API_KEY:
            return None
        try:
            from elevenlabs import ElevenLabs  # type: ignore[import]

            def _sync() -> bytes:
                client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
                gen = client.text_to_speech.convert(
                    voice_id=ELEVENLABS_VOICE_ID,
                    text=text,
                    model_id="eleven_turbo_v2",
                    output_format="mp3_44100_128",
                )
                return b"".join(gen)

            return await asyncio.get_event_loop().run_in_executor(None, _sync)
        except Exception as exc:
            print(f"[TTS] ElevenLabs failed: {exc}")
            return None

    async def _openai_tts(self, text: str) -> bytes | None:
        """OpenAI TTS-1."""
        if not OPENAI_API_KEY:
            return None
        try:
            from openai import OpenAI  # type: ignore[import]

            def _sync() -> bytes:
                client = OpenAI(api_key=OPENAI_API_KEY)
                resp = client.audio.speech.create(
                    model="tts-1", voice="nova", input=text, response_format="mp3"
                )
                return resp.read()

            return await asyncio.get_event_loop().run_in_executor(None, _sync)
        except Exception as exc:
            print(f"[TTS] OpenAI TTS failed: {exc}")
            return None

    # ── Offline fallback: pyttsx3 ─────────────────────────────────────────────

    async def _pyttsx3_speak(self, text: str) -> None:
        """Speak directly via pyttsx3 (no file; blocks until done)."""
        try:
            import pyttsx3  # type: ignore[import]

            def _sync() -> None:
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()

            await asyncio.get_event_loop().run_in_executor(None, _sync)
        except Exception as exc:
            # Absolute last resort
            print(f"[TTS] pyttsx3 failed ({exc}); falling back to Windows SAPI")
            await self._sapi_speak(text)

    # ── Windows SAPI (PowerShell) ─────────────────────────────────────────────

    async def _sapi_speak(self, text: str) -> None:
        if sys.platform != "win32":
            print(f"[Nova] {text}")
            return
        safe = text.replace('"', "'")
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            f'Add-Type -AssemblyName System.speech; '
            f'$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
            f'$s.Speak("{safe}")',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    # ── Playback ──────────────────────────────────────────────────────────────

    async def _play(self, path: Path) -> None:
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"Add-Type -AssemblyName PresentationCore; "
                f"$m = New-Object System.Windows.Media.MediaPlayer; "
                f"$m.Open([System.Uri]::new('{path.as_uri()}')); "
                f"$m.Play(); Start-Sleep -Milliseconds 10000",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        elif sys.platform == "darwin":
            proc = await asyncio.create_subprocess_exec(
                "afplay", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        else:
            # Linux: try ffplay, fall back to pyttsx3
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ffplay", "-nodisp", "-autoexit", str(path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except FileNotFoundError:
                await self._pyttsx3_speak(path.stem)  # best we can do

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _cache_path(self, text: str) -> Path:
        key = f"{text}|{EDGE_TTS_VOICE}|{TTS_ENGINE}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return TTS_CACHE_DIR / f"{digest}.{_AUDIO_FORMAT}"

    def _temp_path(self, text: str) -> Path:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        return TTS_CACHE_DIR / f"_tmp_{digest}.{_AUDIO_FORMAT}"

    def _evict_if_needed(self) -> None:
        """Remove oldest cache entries when over TTS_CACHE_MAX_SIZE."""
        files = sorted(TTS_CACHE_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        while len(files) >= TTS_CACHE_MAX_SIZE:
            try:
                files.pop(0).unlink()
            except Exception:
                break


# ── Provider order builder ────────────────────────────────────────────────────

_PROVIDER_MAP = {
    "edge":        TTS._edge_tts,
    "elevenlabs":  TTS._elevenlabs,
    "openai":      TTS._openai_tts,
}

def _build_provider_order(preferred: str):
    """Return provider callables with *preferred* engine first."""
    order = [preferred] + [k for k in ("edge", "elevenlabs", "openai") if k != preferred]
    return [_PROVIDER_MAP[k] for k in order if k in _PROVIDER_MAP]

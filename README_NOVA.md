# Nova v2

> Voice-gated personal desktop AI agent for Windows

Nova listens for a wake word (or a double-clap), verifies it's you speaking, transcribes what you say, and orchestrates a full set of tools — browser, files, apps, screen, email, calendar, and more — to carry out your request.

**Free by default.** The minimum setup requires only one API key (OpenAI for the AI brain). Wake-word detection and text-to-speech both work offline with no paid subscriptions.

---

## Quick Start (Mock Mode — no API keys needed)

```bash
# 1. Clone and enter the repo
cd ai-BOT

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows

# 3. Install core dependencies
pip install python-dotenv rich pydantic

# 4. Copy the env template
copy .env.example .env

# 5. Enable mock mode in .env
#    MOCK_MODE=true

# 6. Run Nova
python -m nova.main
```

In mock mode:
- **Enter** simulates a voice wake
- **s + Enter** simulates a double-clap wake
- All STT/TTS/API calls are replaced by keyboard input and console output

---

## Minimum Setup (live mode — one key)

```bash
pip install -r requirements.txt
playwright install chromium
```

`.env`:
```env
MOCK_MODE=false
OPENAI_API_KEY=sk-...   # Required — powers the AI brain
```

That's it. Wake-word detection uses **openwakeword** (free, offline) and TTS uses **Microsoft Edge Neural TTS** (free, internet required). No Picovoice key, no ElevenLabs key.

---

## Full Installation

### Prerequisites (Windows)

| Requirement | Notes |
|---|---|
| Python 3.10+ | [python.org](https://python.org) |
| Tesseract OCR | [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) — needed for screen OCR |
| PortAudio | `pipwin install pyaudio` — needed for mic input |
| ffmpeg | [ffmpeg.org](https://ffmpeg.org) — needed for voice_input transcription from browser |
| CUDA (optional) | Speeds up Whisper STT significantly |

```bash
pip install -r requirements.txt
playwright install chromium
```

---

## Voice Enrollment

Before speaker verification works, enroll your voice once:

```bash
python -m nova.setup.enroll
```

Records 10 phrases, extracts speaker embeddings, saves voiceprint to `data/voiceprints/owner.npy`.

---

## Google Integration (Gmail + Calendar)

```bash
# 1. Create a project at console.cloud.google.com
#    Enable: Gmail API + Google Calendar API
#    Download OAuth2 credentials → save as data/credentials/google_credentials.json

# 2. Run the setup wizard
python -m nova.setup.configure_google
```

Token is saved automatically. No GMAIL_API_KEY — it's OAuth2 only.

---

## Running

```bash
# Voice pipeline (main loop)
python -m nova.main

# REST + WebSocket server + Three.js orb UI
uvicorn nova.server:app --port 8765

# Three.js frontend (in a separate terminal)
cd frontend && npm install && npm run dev
# Visit: http://localhost:5173
```

---

## Wake Methods

Both methods can run simultaneously (`WAKE_METHODS=voice,clap`).

| Method | Engine | Notes |
|---|---|---|
| Voice wake | **openwakeword** (free, offline) | Built-in: `hey_jarvis`, `alexa`, `hey_mycroft` |
| Double-clap | Built-in RMS detector | Two claps 300–700 ms apart |

To train a custom `hey_nova` model: [github.com/dscripka/openWakeWord](https://github.com/dscripka/openWakeWord)

---

## TTS Engines

Provider chain tries each in order until one succeeds:

| Engine | Cost | Notes |
|---|---|---|
| **edge-tts** (default) | Free | Microsoft Edge Neural TTS, internet required |
| **pyttsx3** | Free | Fully offline Windows/Mac SAPI |
| **ElevenLabs** | Paid | Set `ELEVENLABS_API_KEY` |
| **OpenAI TTS-1** | Paid | Uses `OPENAI_API_KEY` |

Default voice: `en-GB-SoniaNeural` (natural British female). Change with `EDGE_TTS_VOICE=`.

---

## Architecture

```
nova/
├── main.py              ← Async pipeline loop (wake → verify → STT → agent → TTS)
├── config.py            ← Typed config from .env
├── server.py            ← FastAPI + WebSocket backend
├── wake/
│   ├── wakeword.py      ← openwakeword (default) or Porcupine (optional)
│   ├── clap_detector.py ← Double-clap RMS detector
│   ├── vad.py           ← Silero VAD
│   ├── speaker_verify.py← ECAPA-TDNN identity check
│   └── liveness.py      ← 3-word anti-spoofing challenge
├── speech/
│   └── stt.py           ← faster-whisper (Whisper base.en, runs locally)
├── brain/
│   ├── agents.py        ← OpenAI Agents SDK orchestrator + specialist sub-agents
│   ├── proactive.py     ← Contextual follow-up suggestions
│   └── system_prompt.py
├── tools/
│   ├── browser_tool.py  ← Playwright web automation
│   ├── file_tool.py     ← Filesystem read/write
│   ├── terminal_tool.py ← Sandboxed shell commands
│   ├── app_tool.py      ← Windows app launcher
│   ├── screen_tool.py   ← mss + pytesseract OCR
│   ├── email_tool.py    ← Gmail (OAuth2)
│   ├── calendar_tool.py ← Google Calendar (OAuth2)
│   ├── cua_tool.py      ← Computer-use visual automation (pyautogui)
│   ├── document_tool.py ← DOCX / XLSX / PDF read-write
│   └── clipboard_tool.py
├── memory/
│   ├── store.py         ← SQLite + FTS5 episodic memory
│   └── defaults.py      ← Bootstrap preferences
├── voice/
│   └── tts.py           ← edge-tts → ElevenLabs → OpenAI → pyttsx3 → SAPI
├── routines/
│   └── scheduler.py     ← Morning briefing + end-of-day + custom routines
├── safety/
│   ├── governance.py    ← SAFE/MODERATE/HIGH/CRITICAL/BLOCKED risk classifier
│   ├── guardrails.py    ← Input filtering + output redaction
│   ├── logger.py        ← JSONL audit log
│   └── killswitch.py    ← Ctrl+Shift+K hardware stop
├── ui/
│   └── tray.py          ← System tray icon (4 states)
├── utils/
│   ├── retry.py         ← Exponential back-off + fallback chains
│   └── timing.py        ← Pipeline stage timer + performance log
└── setup/
    ├── enroll.py        ← Voice enrollment wizard
    └── configure_google.py ← Google OAuth2 setup

frontend/               ← Three.js orb UI (Vite + TypeScript)
scripts/
└── red_team.py         ← 32 automated safety tests
```

---

## WebSocket Protocol

The frontend communicates with Nova over `ws://localhost:8765/ws`.

**Client → Server:**

| type | fields | description |
|---|---|---|
| `ping` | — | keepalive |
| `text_input` | `text` | send a text command |
| `voice_input` | `audio` (base64 WebM) | mic recording to transcribe |
| `approval` | `approved` (bool) | respond to approval_required |

**Server → Client:**

| type | fields | description |
|---|---|---|
| `connected` | `mock_mode` | handshake on connect |
| `pong` | — | ping reply |
| `state` | `state` | orb state: idle/listening/thinking/speaking/error |
| `transcribed` | `text` | STT result from voice_input |
| `response` | `text`, `audio?` | agent reply; audio is base64 MP3 |
| `approval_required` | `description`, `risk_level`, `prompt` | user must approve HIGH/CRITICAL action |
| `blocked` | `detail` | guardrails or policy blocked the request |
| `error` | `detail` | server error |

---

## Safety Model

| Risk Level | Examples | Action |
|---|---|---|
| SAFE | Web search, read email, read file | Proceed silently |
| MODERATE | Create file, launch app, draft email | Log and proceed |
| HIGH | Send email, create calendar event | Confirmation required |
| CRITICAL | rm -rf, delete calendar, sudo | Blocked by default |
| BLOCKED | Dangerous shell patterns, injections | Always refused |

Kill switch: **Ctrl+Shift+K** stops Nova immediately.

---

## Scheduled Routines

Two built-in routines (configurable, can be disabled):

| Routine | Default time |
|---|---|
| Morning briefing | 09:00 daily — weather, calendar, unread emails |
| End-of-day summary | 18:00 daily — completed tasks, reminders |

Add custom routines via REST: `POST /routines` or from natural language commands.

---

## Mock Mode Reference

| Component | Real | Mock |
|---|---|---|
| Wake word | openwakeword mic listener | Enter key |
| Double-clap | Mic RMS detector | s + Enter |
| VAD | Silero VAD | Fixed-duration |
| Speaker verify | ECAPA cosine similarity | Always passes |
| STT | faster-whisper (local) | Keyboard input |
| Agent | GPT-4o + Agents SDK | Rule-based dispatcher |
| TTS | edge-tts / pyttsx3 | Prints `[Nova] {text}` |

---

## Environment Variables Reference

See `.env.example` for the full reference with comments. Minimum required:

```env
OPENAI_API_KEY=sk-...
```

Everything else has sensible free defaults.

---

## License

MIT

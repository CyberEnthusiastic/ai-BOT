# Nova v2 — Phase 1

> Voice-gated personal desktop AI agent for Windows

Nova listens for a wake word, verifies it's you speaking, transcribes what you say, and orchestrates a set of local tools (browser, files, apps, screen) to carry out your request — all with full mock/fallback support so you can run without any API keys.

---

## Quick Start (Mock Mode — no keys needed)

```bash
# 1. Clone and enter the repo
cd ai-BOT

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows

# 3. Install dependencies (core subset works without GPU/special libs)
pip install python-dotenv rich pydantic

# 4. Copy the env template
copy .env.example .env          # Windows
# The default .env has MOCK_MODE=true already

# 5. Run Nova
python -m nova.main
```

In mock mode you'll see prompts like:
```
[wake] > hey nova
[you]  > open notepad
[Nova] Launched notepad.
```

---

## Full Installation

### Prerequisites (Windows)

| Requirement | Install |
|---|---|
| Python 3.10+ | [python.org](https://python.org) |
| Tesseract OCR | [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) |
| PortAudio (for pyaudio) | `pipwin install pyaudio` |
| CUDA (optional, GPU) | [pytorch.org](https://pytorch.org/get-started/locally/) |

```bash
pip install -r requirements.txt
playwright install chromium
```

### API Keys

Edit `.env` and fill in:

```env
MOCK_MODE=false
OPENAI_API_KEY=sk-...
PICOVOICE_API_KEY=...
ELEVENLABS_API_KEY=...
```

---

## Voice Enrollment

Before speaker verification works you need to enroll your voice:

```bash
python -m nova.setup.enroll
```

This records 10 phrases, extracts ECAPA-TDNN embeddings, and saves your voiceprint to `data/voiceprints/owner.npy`.

---

## Running

```bash
# Main voice loop
python -m nova.main

# REST + WebSocket server (Phase 2 orb UI)
uvicorn nova.server:app --reload --port 8765

# One-off text command (no voice)
curl -X POST http://localhost:8765/text -H "Content-Type: application/json" \
     -d '{"text": "list files on my desktop"}'
```

---

## Architecture

```
nova/
├── main.py          ← Main async loop
├── config.py        ← Config / env loader
├── server.py        ← FastAPI + WebSocket backend
├── wake/
│   ├── wakeword.py  ← Porcupine or keyboard fallback
│   ├── vad.py       ← Silero VAD or fixed-duration recording
│   ├── speaker_verify.py  ← ECAPA-TDNN identity verification
│   └── liveness.py  ← 3-word anti-spoofing challenge
├── speech/
│   └── stt.py       ← faster-whisper or keyboard fallback
├── brain/
│   ├── agents.py    ← OpenAI Agents SDK orchestrator + sub-agents
│   └── system_prompt.py
├── tools/
│   ├── browser_tool.py   ← Playwright
│   ├── file_tool.py      ← Filesystem ops
│   ├── terminal_tool.py  ← Sandboxed shell
│   ├── app_tool.py       ← Windows app launcher
│   └── screen_tool.py    ← mss + pytesseract
├── memory/
│   ├── store.py     ← SQLite + FTS5
│   └── defaults.py  ← Bootstrap preferences
├── voice/
│   └── tts.py       ← ElevenLabs → OpenAI → pyttsx3 → mock
├── safety/
│   ├── governance.py  ← SAFE/MODERATE/HIGH/CRITICAL/BLOCKED
│   ├── guardrails.py  ← Input filtering + output redaction
│   ├── logger.py      ← JSONL audit log
│   └── killswitch.py  ← Ctrl+Shift+K hardware stop
└── setup/
    └── enroll.py    ← Voice enrollment wizard
```

---

## Safety Model

| Risk Level | Trigger | Action |
|---|---|---|
| SAFE | Read-only queries | Proceed silently |
| MODERATE | File reads, browser navigation | Log and proceed |
| HIGH | Writes, sends, installs | Verbal confirmation required |
| CRITICAL | Deletions, credentials, git push | Liveness challenge required |
| BLOCKED | Dangerous patterns, injections | Unconditionally refused |

Kill switch: **Ctrl+Shift+K** stops Nova immediately from anywhere.

---

## Mock Mode Reference

All external services degrade gracefully:

| Component | Real | Mock |
|---|---|---|
| Wake word | Porcupine mic listener | Press Enter / type "hey nova" |
| VAD | Silero VAD | Returns silence (STT uses text input) |
| Speaker verify | ECAPA cosine similarity | Always returns True |
| STT | faster-whisper | Keyboard text input |
| Orchestrator | GPT-4o + Agents SDK | Rule-based pattern dispatcher |
| TTS | ElevenLabs / OpenAI / SAPI | Prints `[Nova] {text}` |

---

## Phase 2 Preview

- Floating orb UI (Electron / React)
- Proactive reminders and notifications
- Calendar and email integration
- Long-term memory with semantic search
- Multi-turn conversation context window

---

## License

MIT

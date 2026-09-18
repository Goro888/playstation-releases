# JARVIS — local-first AI operating assistant

A layered JARVIS-style assistant that runs on **your** Windows machine:
wake word → speech-to-text → local LLM → real Windows actions → spoken reply,
behind a dark HUD.

```
Microphone ─▶ openWakeWord ─▶ Whisper ─▶ Router ─┬─▶ Ollama / Qwen   (local)
   “Hey JARVIS”                                   └─▶ OpenAI-compatible (cloud, optional)
                                                        │
                                                        ▼
                                                  Agent core
                                            (plan · tools · permissions)
                                                        │
                     ┌────────────────┬─────────────────┼──────────────┐
                     ▼                ▼                 ▼              ▼
              Windows apps      Files & folders    Memory (SQLite)   Web search
              UI Automation     Clipboard          Tasks / prefs     Screenshots
                     │                │                 │              │
                     └────────────────┴────────┬────────┴──────────────┘
                                               ▼
                                          Piper TTS ─▶ Speaker
                                               │
                                     SSE events ─▶ JARVIS HUD
```

> **Note:** this repository used to hold a PlayStation releases demo app. It has
> been repurposed wholesale into JARVIS; the git history still contains the
> original commit.

---

## Why this design

| Decision | Reason |
| --- | --- |
| **Layered, not one model** | STT, reasoning, TTS and control are separate problems with separate best tools |
| **Local by default, cloud optional** | privacy + offline capability; cloud only for deep research / heavy reasoning |
| **Ollama + Qwen** | a single local server with OpenAI-style **tool calling**, so the model can *act* instead of describing actions |
| **openWakeWord** | ships a `hey jarvis` model and runs on ONNX Runtime — far cheaper than keeping Whisper listening |
| **whisper.cpp** | CPU/GPU/NPU builds for Windows with built-in Arabic support |
| **Piper** | fast, fully local neural voices (a CLI + a voice `.onnx`, no cloud) |
| **Windows UI Automation** | real interaction with apps (click *that* button), not just `os.system()` |
| **Permission manager** | the model requests *named* tools; nothing dangerous runs without confirmation |
| **Offline brain** | keeps every tool usable before any model is downloaded |

---

## Quick start

### Windows

```powershell
git clone <this-repo> jarvis
cd jarvis
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1   # downloads models too
.venv\Scripts\python -m jarvis doctor                                  # verify every layer
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1               # bridge + HUD
```

### Linux / macOS (development)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/dev.sh            # bridge on 8770, HUD on 5173
python -m jarvis doctor
```

Open the HUD, type `system status`, or say **“Hey JARVIS”**.

---

## Try it without any model installed

```bash
.venv/bin/python -m jarvis chat --once "system status"
.venv/bin/python -m jarvis chat --once "remember that my editor is VS Code"
.venv/bin/python -m jarvis chat --once "what do you remember about my editor"
.venv/bin/python -m jarvis chat --once "ما هي حالة الجهاز"      # Arabic works too
```

JARVIS answers with real data from real tools even with no LLM attached — that
is the offline brain doing its job.

---

## Every layer

| Layer | Technology | Where |
| --- | --- | --- |
| Desktop UI | React + Vite dark HUD | `hud/` |
| Core runtime | Python 3.10–3.13 (3.11 recommended) | `jarvis/` |
| Local LLM | Ollama + Qwen (`qwen3.5:4b` default) | `jarvis/models/ollama.py` |
| Cloud tier | any OpenAI-compatible API · Foundry Local | `jarvis/models/openai_compatible.py` |
| Offline fallback | bilingual intent → tool matcher | `jarvis/models/offline.py` |
| Router | local-first, cloud for research/vision/long prompts | `jarvis/core/router.py` |
| Wake word | openWakeWord (`hey jarvis`) | `jarvis/voice/wake_word.py` |
| STT | whisper.cpp / faster-whisper (Arabic included) | `jarvis/voice/stt.py` |
| TTS | Piper (OHF-voice/piper1-gpl) · pyttsx3 fallback | `jarvis/voice/tts.py` |
| Memory | SQLite + FTS5 (+ optional embeddings) | `jarvis/core/memory.py` |
| Windows control | PowerShell, UI Automation, psutil, mss | `jarvis/tools/` |
| Permissions | safe / sensitive / dangerous + human confirmation | `jarvis/core/permissions.py` |
| API | FastAPI REST + SSE | `jarvis/bridge/server.py` |

29 tools across 8 categories: `system`, `files`, `clipboard`, `ui`, `screen`,
`web`, `memory`, `misc`.

---

## Commands

```bash
python -m jarvis serve                 # API bridge (default 127.0.0.1:8770)
python -m jarvis serve --host 0.0.0.0  # expose on the LAN (only if you trust it)
python -m jarvis chat                  # terminal chat
python -m jarvis chat --voice          # wake word → STT → agent → Piper
python -m jarvis chat --once "open chrome"
python -m jarvis listen --respond       # one utterance from the microphone
python -m jarvis say "Systems nominal, sir."
python -m jarvis doctor                # which layers are ready
python -m jarvis tools                 # list every tool + risk level
python -m jarvis memory --remember "the JARVIS repo is on the D: drive"
python -m jarvis memory --recall "JARVIS"
python -m jarvis run system_status     # call a tool directly (permission-gated)
python -m jarvis config                # print a starter YAML
```

---

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` · `/api/status` · `/api/system` | liveness, layer status, telemetry |
| `GET` | `/api/events` | **SSE** stream of every event (drives the HUD) |
| `POST` | `/api/chat` | one turn: `{ message, session, images, force }` |
| `GET` | `/api/tools` · `POST /api/tools/call` | catalogue and direct execution |
| `GET` | `/api/permissions` · `POST /api/permissions/{id}/approve\|deny` | confirmation queue |
| `GET/POST/DELETE` | `/api/memory` · `/api/memory/{id}` · `/api/tasks` | facts and tasks |
| `POST` | `/api/voice/start` · `/stop` · `/speak` · `/listen` | voice loop control |
| `GET` | `/api/config` | redacted running configuration |

Built HUD assets are served from `/` when `hud/dist` exists.

---

## Security model

The model never touches Windows directly.

```
LLM ─▶ Permission Manager ─▶ Approved Tool ─▶ Windows
```

| Risk | Behaviour | Examples |
| --- | --- | --- |
| `safe` | runs immediately | open Chrome, read a file, system status, screenshot |
| `sensitive` | asks first | close an app, write a file, type text, click a control |
| `dangerous` | asks + needs `allow_shell` | delete a file, run a shell command |

File tools refuse any path outside `tools.allowed_roots`, and every request is
logged to the activity feed and `~/.jarvis/logs/jarvis.log`.

---

## Repository layout

```
jarvis/                 Python core (agent, router, permissions, memory)
├── core/               agent loop · router · permissions · memory · prompts
├── models/             ollama · openai-compatible · offline brain
├── tools/              29 tools + platform helpers (PowerShell, UI Automation)
├── voice/              wake word · STT · TTS · pipeline
├── bridge/             FastAPI REST + SSE
└── cli.py              python -m jarvis …
hud/                    React + Vite HUD
config/jarvis.example.yaml
scripts/                install_windows.ps1 · dev.ps1 · dev.sh · jarvis.bat
docs/                   ARCHITECTURE · WINDOWS_SETUP · PHASES
tests/                  101 pytest tests
```

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

---

## Arabic / RTL

The HUD, the offline brain, Whisper and memory search all handle Arabic:

```bash
python -m jarvis chat --once "افتح المتصفح"
python -m jarvis chat --once "تذكر أن اجتماع الفريق غداً الساعة العاشرة"
python -m jarvis chat --once "ماذا تتذكر"
```

Set `persona.language: ar` to force Arabic replies, and use an Arabic-capable
model plus an Arabic Piper voice (e.g. `ar_JO-kareem-medium`).

---

## Roadmap

See [`docs/PHASES.md`](docs/PHASES.md) — phases 1–5 and 7 are implemented;
phase 6 (explicit planner, research agent, scheduler, document memory) is next.

## License

MIT — see [LICENSE](LICENSE).

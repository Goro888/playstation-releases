# Build phases

Where the project stands, and what comes next. Phases 1–5 and 7 are implemented
in this repository; phase 6 is partially implemented (the tools exist, the
planner is deliberately simple).

| Phase | Scope | Status |
| --- | --- | --- |
| 1 — Brain | Python core, Ollama/Qwen, routing, basic chat | ✅ `jarvis/core`, `jarvis/models` |
| 2 — Voice | Microphone → wake word → Whisper → LLM → Piper | ✅ `jarvis/voice` (engines optional) |
| 3 — Tools | Apps, files, folders, clipboard, browser, PowerShell | ✅ 29 tools, 8 categories |
| 4 — Computer agent | Screenshots, vision, Windows UI Automation | ✅ `capture_screen`, `analyze_screen`, `click_control`, `type_text`, `send_hotkey`, `focus_window` |
| 5 — Memory | Personal facts, documents, conversation history | ✅ SQLite + FTS5, tasks, prefs, optional vectors |
| 6 — Intelligence | Task planning, multi-step actions, research, schedules | 🟡 multi-step tool loop ✅ · planner ⚠️ simple · research agent 🔜 |
| 7 — HUD | Desktop window, circular core, waveform, telemetry | ✅ `hud/` (React) |

## Phase 6 roadmap

- [ ] **Planner module** — emit an explicit ordered plan (`core/planner.py`) and
      render it in the HUD before execution, instead of a single implicit loop.
- [ ] **Research agent** — recursive web search + fetch + summarise with
      citations, routed to the cloud tier when enabled.
- [ ] **Scheduler** — cron-like tasks stored in SQLite, driven by a background
      asyncio loop (`jarvis schedule add "every monday 09:00" "..." `).
- [ ] **Document memory** — index a folder (PDF/DOCX/TXT/MD) into the fact
      store with embeddings for real semantic recall.
- [ ] **Skills** — loadable, user-authored tool packs (`~/.jarvis/skills/*.py`).

## Phase 7+ (HUD polish)

- [ ] WinUI 3 / Tauri shell that hosts the same HUD as a frameless window with
      always-on-top + `Ctrl+Space` summon.
- [ ] Waveform driven by real microphone amplitude (currently synthetic).
- [ ] Local audio playback of Piper output in the browser (`/api/audio` exists).
- [ ] Multi-session transcripts with per-project memory scopes.

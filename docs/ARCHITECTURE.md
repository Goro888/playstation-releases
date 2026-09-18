# JARVIS — Architecture

JARVIS is **layered**, not monolithic. Each layer can be upgraded (or removed)
without touching the others, and every layer degrades gracefully — the system
is usable with nothing but Python installed, and grows as you add models.

```
                    ┌──────────────────────────┐
                    │        JARVIS HUD        │  hud/  (React + Vite)
                    │  dark HUD · SSE events   │
                    └────────────┬─────────────┘
                                 │  HTTP + SSE (/api/*)
                    ┌────────────▼─────────────┐
                    │      BRIDGE (FastAPI)    │  jarvis/bridge
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │   AGENT CORE (loop)      │  jarvis/core/agent.py
                    │  plan → tool → observe   │
                    └───┬──────────┬───────┬───┘
                        │          │       │
        ┌───────────────▼──┐  ┌────▼────┐ ┌▼──────────────────┐
        │   ROUTER         │  │ MEMORY  │ │ PERMISSIONS       │
        │ local/cloud/     │  │ SQLite  │ │ safe / confirm /  │
        │ offline          │  │ + FTS5  │ │ deny              │
        └───┬──────────┬───┘  └─────────┘ └────────┬──────────┘
            │          │                            │
   ┌────────▼──┐  ┌────▼──────┐            ┌────────▼─────────┐
   │  Ollama   │  │  Cloud    │            │   TOOL LAYER     │
   │  Qwen     │  │ OpenAI/   │            │ system · files · │
   │  (local)  │  │ Foundry   │            │ clipboard · ui · │
   └───────────┘  └───────────┘            │ screen · web ·   │
                                           │ memory · misc    │
   ┌───────────────────────────────────┐   └────────┬─────────┘
   │ VOICE  wake → STT → agent → TTS   │            │
   │ openWakeWord · Whisper · Piper    │   ┌────────▼─────────┐
   └───────────────────────────────────┘   │  Windows         │
                                           │  PowerShell ·    │
                                           │  UI Automation   │
                                           └──────────────────┘
```

## Modules

| Path | Responsibility |
| --- | --- |
| `jarvis/config.py` | Layered config: defaults → YAML → `JARVIS_*` env → CLI flags |
| `jarvis/events.py` | Pub/sub bus + SSE ring buffer (drives the whole HUD) |
| `jarvis/core/agent.py` | The loop: prompt → model → tool calls → permission gate → observation → answer |
| `jarvis/core/router.py` | Picks local (Ollama/Qwen), cloud, or the offline brain per request |
| `jarvis/core/permissions.py` | Risk classification + human confirmation (futures resolved by the UI) |
| `jarvis/core/memory.py` | Facts, conversations, tasks, preferences (SQLite + FTS5, optional vectors) |
| `jarvis/models/ollama.py` | Ollama `/api/chat` with OpenAI-style tool calling + vision |
| `jarvis/models/openai_compatible.py` | OpenAI / Azure / Groq / OpenRouter / **Foundry Local** |
| `jarvis/models/offline.py` | Deterministic bilingual intent → tool matcher (zero-model fallback) |
| `jarvis/tools/*` | 29 tools across system, files, clipboard, UI, screen, web, memory, misc |
| `jarvis/voice/*` | openWakeWord → Whisper (whisper.cpp / faster-whisper) → Piper |
| `jarvis/bridge/server.py` | FastAPI REST + SSE: chat, tools, permissions, memory, system, voice |
| `hud/` | React HUD: core visualiser, waveform, telemetry, activity, confirmations |

## Request lifecycle

1. **Input** — HUD, CLI, or the voice loop calls `Agent.handle(text)`.
2. **Context** — memory is searched (`FTS5` over facts) and injected into the
   system prompt along with the tool catalogue.
3. **Routing** — the router picks a backend:
   * `local` when Ollama has a model (default),
   * `cloud` for long/deep requests when a cloud tier is enabled,
   * `offline` when nothing else is reachable.
4. **Tool loop** (max `agent.max_steps` rounds):
   * the model returns tool calls,
   * each call passes the **permission gate** — `safe` runs, `sensitive`
     parks until a human confirms in the HUD/CLI/API, `dangerous` needs shell
     access enabled,
   * results are truncated and appended as tool messages.
5. **Answer** — the final text is persisted to memory, published as a `message`
   event, spoken by Piper when the voice loop is active.

## Events (SSE `/api/events`)

`status · user_message · route · thinking · tool_call · tool_result ·
permission_request · permission_granted · permission_denied · transcript ·
spoken · wake_detected · wake_score · audio_level · memory_added · message · error`

The HUD subscribes once and renders everything from this stream; there is no
polling for conversation state.

## Why the offline brain exists

Without it, a fresh Windows install with no model yet produces a dead assistant.
The offline brain understands a fixed but useful set of bilingual commands
(open/close apps, files, screenshots, time, system status, web search,
remember/recall, tasks) and drives **the exact same tools** as the LLM. That
means the tools, permissions, memory and HUD are all testable end-to-end before
a single model is downloaded.

It is a safety net, not a substitute: connect Ollama and every one of those
commands keeps working, now with reasoning, chaining and free-form answers.

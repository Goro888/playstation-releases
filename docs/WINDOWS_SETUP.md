# JARVIS on Windows — setup guide

Everything below is local-first. Nothing leaves your machine unless you
explicitly enable the cloud tier.

## 0. Prerequisites

| Requirement | Notes |
| --- | --- |
| Windows 10/11 | UI Automation tools need Windows; the rest runs anywhere |
| Python 3.11 | OpenJarvis-style stacks support **3.10–3.13**; 3.11 is the safe pick |
| Node 20+ | Only for the HUD (`hud/`) |
| ~10 GB disk | Models are downloaded separately from the app |

## 1. Install

```powershell
git clone <this-repo> jarvis
cd jarvis
powershell -ExecutionPolicy Bypass -File scripts\install_windows.ps1
```

The installer is resumable and non-fatal: each stage (Python env, Ollama,
whisper.cpp, Piper, UI Automation, config) reports OK / skipped independently.

Useful switches:

```powershell
.\scripts\install_windows.ps1 -Model qwen3.5:9b      # bigger brain (needs a GPU)
.\scripts\install_windows.ps1 -WhisperModel small    # better Arabic/English STT
.\scripts\install_windows.ps1 -SkipModels            # code only, download models later
.\scripts\install_windows.ps1 -NoVoice               # text-only install
```

### Manual install (if you prefer)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
winget install Ollama.Ollama
ollama pull qwen3.5:4b
ollama pull qwen2.5vl:7b          # vision, for "what's on my screen?"
```

## 2. Check every layer

```powershell
.venv\Scripts\python -m jarvis doctor
```

```
[ OK ] platform           Python 3.11.9 on Windows-10-10.0.26100-SP0
[ OK ] local brain        qwen3.5:4b @ http://127.0.0.1:11434 (installed: qwen3.5:4b, ...)
[ OK ] tools              clipboard:2, files:5, memory:6, misc:2, screen:2, system:5, ui:5, web:2
[ OK ] memory             C:\Users\you\.jarvis\memory.db
[ OK ] wake word          hey jarvis via openwakeword
[ OK ] speech-to-text     whisper_cpp (base, lang=auto)
[ OK ] text-to-speech     piper (en_US-lessac-medium)
[ OK ] microphone         sounddevice
```

## 3. Run

```powershell
# API bridge (port 8770)
.venv\Scripts\python -m jarvis serve

# HUD (port 5173) — in a second terminal
cd hud
npm install
npm run dev

# …or everything at once
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

# …or terminal only, no HUD
.venv\Scripts\python -m jarvis chat --voice
```

Then: **"Hey JARVIS"** → *"Yes, sir."* → **"open chrome"**.

## 4. The voice stack

### Wake word — openWakeWord

```powershell
.venv\Scripts\python -m pip install openwakeword sounddevice numpy
```

The `hey jarvis` model ships with the package, so no download is needed.
Raise `voice.wake_threshold` (default `0.5`) if you get false activations;
lower it if JARVIS ignores you.

### Speech-to-text — Whisper

Two supported paths:

* **whisper.cpp** (default) — download the `win-x64` release, put
  `whisper-cli.exe` on PATH (or set `voice.stt_binary` to its full path), then
  drop `ggml-base.bin` (or `small`/`medium`) into `%USERPROFILE%\.jarvis\models`.
* **faster-whisper** — `pip install faster-whisper`, set
  `voice.stt_engine: faster_whisper` and `voice.stt_model: small`.

Arabic works out of the box (`voice.stt_language: ""` = auto-detect, or `"ar"`).

### Text-to-speech — Piper

Piper moved to **OHF-voice/piper1-gpl**. Put `piper.exe` on PATH (or set
`voice.piper_binary`), then place `<voice>.onnx` **and** `<voice>.onnx.json`
under `%USERPROFILE%\.jarvis\models\piper`. Browse voices at
<https://rhasspy.github.io/piper-samples/> — Arabic voices such as
`ar_JO-kareem-medium` work the same way.

No voice yet? Set `voice.tts_engine: pyttsx3` + `pip install pyttsx3` for the
built-in SAPI5 voice, or `none` to stay silent and read replies in the HUD.

## 5. Windows control

| Layer | Used for | Requirement |
| --- | --- | --- |
| PowerShell `Start-Process` / `Stop-Process` | open/close apps and files | built in |
| Get-Process / WScript.Shell | list + focus windows, type text, hotkeys | built in |
| **UI Automation** | click buttons by name (`click_control`) | `pip install uiautomation` |
| mss / Pillow | screenshots | in `requirements.txt` |
| psutil | CPU/RAM/disk telemetry, process list | in `requirements.txt` |

Without `uiautomation` you still get window listing, focusing, typing and
hotkeys through PowerShell — only element-level clicking is unavailable.

## 6. Security

The model can **never** run raw shell commands unless you opt in.

```yaml
security:
  mode: confirm-sensitive   # safe tools run, sensitive ones ask first
  allow_shell: false        # keep false unless you need run_command
  auto_approve: [open_application, system_status, get_time]
  denied: [run_command]
```

Risk classes:

* **safe** — open an app, read a file, check the time, take a screenshot
* **sensitive** — close an app, write a file, type text, click a UI element
* **dangerous** — delete a file, run a shell command

Sensitive/dangerous calls appear in the HUD (and the CLI) with **Allow once /
Allow always / Deny**.

## 7. Local vs cloud

`router.mode`:

| Mode | Behaviour |
| --- | --- |
| `offline` | never calls a model; the intent brain runs tools directly |
| `local` | Ollama only |
| `cloud` | cloud tier only (falls back to local if unreachable) |
| `hybrid` | **default** — local first; cloud for long prompts, research keywords, or vision when no local multimodal model is present |

Per-message overrides: prefix with `/cloud` or `/local`.

To use **Foundry Local** (Microsoft's OpenAI-compatible local runtime), point
the cloud section at it:

```yaml
cloud:
  enabled: true
  base_url: http://127.0.0.1:5273/v1
  model: phi-4
```

## 8. Configuration file

`~/.jarvis/config.yaml` (created by the installer from
`config/jarvis.example.yaml`). Environment overrides:

| Variable | Effect |
| --- | --- |
| `JARVIS_HOME` | move models, memory, screenshots and logs |
| `JARVIS_HOST` / `JARVIS_PORT` | bridge bind address |
| `JARVIS_MODEL` | default local model |
| `JARVIS_MODE` | router mode |
| `OLLAMA_HOST` | Ollama endpoint |
| `OPENAI_API_KEY` | cloud tier (when `cloud.enabled: true`) |

## 9. Troubleshooting

| Symptom | Fix |
| --- | --- |
| “offline brain” chip in the HUD | Ollama isn't running or the model isn't pulled — `ollama serve` + `ollama pull qwen3.5:4b` |
| Wake word never fires | check the mic in Windows privacy settings; raise `wake_threshold` down to `0.4`; test with `python -m jarvis listen` |
| Whisper returns empty | confirm `voice.stt_binary` path and that `ggml-*.bin` is in `~/.jarvis/models` |
| No audio | Piper is not on PATH or no `.onnx` voice — see §4 |
| `permission denied` on file tools | the path is outside `tools.allowed_roots` |
| `click_control` unavailable | `pip install uiautomation` |
| Arabic replies look odd | set `persona.language: ar` and use an Arabic-capable model |

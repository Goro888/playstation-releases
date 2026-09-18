"""Command line interface: ``python -m jarvis <command>``."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import sys
from typing import Any, Dict, List, Optional

from .config import JarvisConfig
from .core.agent import JarvisAgent
from .events import ConsoleSink, EventBus

BANNER = r"""
      ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
      ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
      ██║███████║██████╔╝██║   ██║██║███████╗
 ██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
 ╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
        local-first AI operating assistant
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS — local-first AI operating assistant")
    parser.add_argument("--config", help="path to jarvis.yaml")
    parser.add_argument("--log-level", help="DEBUG | INFO | WARNING | ERROR")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every event")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="run the API bridge (used by the HUD)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--no-ui", action="store_true", help="do not serve the built HUD")

    chat = sub.add_parser("chat", help="talk to JARVIS in the terminal")
    chat.add_argument("--session", default="cli")
    chat.add_argument("--voice", action="store_true", help="use the wake-word / microphone loop")
    chat.add_argument("--once", metavar="TEXT", help="run a single utterance and exit")
    chat.add_argument("--cloud", action="store_true", help="force the cloud tier for this session")
    chat.add_argument("--local", action="store_true", help="force the local model for this session")

    say = sub.add_parser("say", help="speak text through the TTS engine")
    say.add_argument("text")

    listen = sub.add_parser("listen", help="record one utterance and print the transcript")
    listen.add_argument("--respond", action="store_true", help="also answer with the agent")

    sub.add_parser("doctor", help="check every layer and print what to install")

    tools = sub.add_parser("tools", help="list registered tools")
    tools.add_argument("--category", default=None)
    tools.add_argument("--json", action="store_true")

    memory = sub.add_parser("memory", help="inspect long-term memory")
    memory.add_argument("--recall", metavar="QUERY")
    memory.add_argument("--remember", metavar="FACT")
    memory.add_argument("--kind", default="note")
    memory.add_argument("--recent", type=int, default=0)
    memory.add_argument("--stats", action="store_true")

    run = sub.add_parser("run", help="execute one tool directly (goes through the permission gate)")
    run.add_argument("tool")
    run.add_argument("--args", default="{}", help="JSON object of arguments")

    sub.add_parser("config", help="print a starter configuration file")
    return parser


# --------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = JarvisConfig.load(args.config)
    if args.log_level:
        cfg.log_level = args.log_level
    if getattr(args, "command", None) == "config":
        print(_starter_yaml())
        return 0

    from .logging_setup import setup_logging

    setup_logging(cfg.log_level, quiet_console=args.command in ("chat", "say"))
    try:
        return asyncio.run(_dispatch(args, cfg))
    except KeyboardInterrupt:  # pragma: no cover
        print("\nGoodbye, sir.")
        return 0


async def _dispatch(args: argparse.Namespace, cfg: JarvisConfig) -> int:
    command = args.command or "chat"

    if command == "doctor":
        return await _doctor(cfg)

    bus = EventBus()
    agent = JarvisAgent.create(cfg, bus)
    sink = ConsoleSink(bus, verbose=args.verbose)

    if command == "serve":
        return await _serve(cfg, agent, bus, args)
    if command == "say":
        from .voice import VoicePipeline

        pipe = VoicePipeline(cfg.voice, bus)
        print(await pipe.say(args.text))
        return 0
    if command == "listen":
        from .voice import VoicePipeline

        pipe = VoicePipeline(cfg.voice, bus)
        text = await pipe.listen_once()
        print(f"You said: {text}")
        sink.drain()
        if args.respond and text:
            result = await agent.handle(text, session="cli")
            print(f"JARVIS: {result.text}")
            sink.drain()
        return 0
    if command == "tools":
        items = agent.registry.describe(categories=[args.category] if args.category else None)
        if args.json:
            print(json.dumps(items, indent=2, ensure_ascii=False))
        else:
            for item in items:
                flag = " " if item["available"] else "x"
                print(f"[{flag}] {item['name']:<20} {item['risk']:<10} {item['description'][:70]}")
        return 0
    if command == "memory":
        return _memory(args, agent)
    if command == "run":
        tool_args = json.loads(args.args)
        result = await agent.run_tool(args.tool, tool_args, session="cli")
        sink.drain()
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.ok else 1
    return await _chat(args, cfg, agent, bus, sink)


# --------------------------------------------------------------------------
async def _serve(cfg: JarvisConfig, agent: JarvisAgent, bus: EventBus, args: argparse.Namespace) -> int:
    import uvicorn

    if args.host:
        cfg.bridge.host = args.host
    if args.port:
        cfg.bridge.port = args.port
    if args.no_ui:
        cfg.bridge.serve_ui = False

    from .bridge import create_app

    app = create_app(cfg, agent, bus)
    print(BANNER)
    print(f"  bridge listening on http://{cfg.bridge.host}:{cfg.bridge.port}")
    print(f"  local model : {cfg.local.model} @ {cfg.local.base_url}")
    print(f"  router mode : {cfg.router.mode}")
    print("  press Ctrl+C to stop\n")
    config = uvicorn.Config(
        app,
        host=cfg.bridge.host,
        port=cfg.bridge.port,
        log_level=cfg.log_level.lower(),
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()
    return 0


async def _chat(args: argparse.Namespace, cfg: JarvisConfig, agent: JarvisAgent, bus: EventBus, sink: ConsoleSink) -> int:
    print(BANNER)
    print(f"  brain : {cfg.router.mode} mode · local={cfg.local.model}")
    print("  type 'exit' to quit, '/tools' to list tools, '/cloud <msg>' to force the cloud tier\n")
    force = "cloud" if getattr(args, "cloud", False) else ("local" if getattr(args, "local", False) else None)

    if args.once:
        result = await agent.handle(args.once, session=args.session, force=force)
        sink.drain()
        print(f"\nJARVIS [{result.backend}/{result.model}]: {result.text}\n")
        return 0

    if args.voice:
        from .voice import VoicePipeline

        pipe = VoicePipeline(cfg.voice, bus)

        async def handler(text: str) -> str:
            result = await agent.handle(text, session=args.session)
            sink.drain()
            print(f"JARVIS: {result.text}")
            return result.text

        print(await pipe.start(handler))
        try:
            while True:
                await asyncio.sleep(1)
                sink.drain()
        except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
            await pipe.stop()
        return 0

    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):  # pragma: no cover
            print("\nGoodbye, sir.")
            return 0
        if not text:
            continue
        if text.lower() in ("exit", "quit", "bye"):
            print("Goodbye, sir.")
            return 0
        if text == "/tools":
            for item in agent.registry.describe():
                print(f"  {item['name']:<20} {item['risk']:<10} {item['description'][:70]}")
            continue
        result = await agent.handle(text, session=args.session, force=force)
        sink.drain()
        print(f"JARVIS [{result.backend}/{result.model}]: {result.text}\n")
        if args.once:
            return 0


def _memory(args: argparse.Namespace, agent: JarvisAgent) -> int:
    memory = agent.memory
    if memory is None:
        print("memory is disabled (memory.enabled=false)")
        return 1
    if args.remember:
        fact = memory.remember(args.remember, kind=args.kind)
        print(f"stored #{fact.id}: {fact.content}")
        return 0
    if args.recall:
        facts = memory.recall(args.recall, limit=10)
        if not facts:
            print("nothing found")
            return 0
        for f in facts:
            print(f"#{f.id} [{f.kind}] {f.content}")
        return 0
    if args.recent:
        for f in memory.recent(args.recent):
            print(f"#{f.id} [{f.kind}] {f.content}")
        return 0
    print(json.dumps(memory.stats(), indent=2))
    return 0


async def _doctor(cfg: JarvisConfig) -> int:
    """Report the health of every layer, with actionable install hints."""
    from .voice import voice_status

    print(BANNER)
    rows: List[tuple] = []

    # python / platform
    rows.append(("platform", True, f"Python {platform.python_version()} on {platform.platform()}"))

    # local model
    from .models.ollama import OllamaBackend

    local = OllamaBackend(cfg.local)
    ok = await local.available()
    models = await local.installed_models() if ok else []
    rows.append(
        (
            "local brain",
            ok,
            f"{local.model} @ {cfg.local.base_url}"
            + (f" (installed: {', '.join(models[:5]) or 'none'})" if ok else " — Ollama not reachable or no model pulled"),
        )
    )
    if not ok:
        rows.append(("  -> fix", False, f"start Ollama, then: ollama pull {cfg.local.model}"))

    # cloud
    from .models.openai_compatible import OpenAICompatibleBackend

    cloud = OpenAICompatibleBackend(cfg.cloud)
    cloud_ok = await cloud.available()
    rows.append(
        (
            "cloud tier",
            cloud_ok if cfg.cloud.enabled else None,
            f"{cfg.cloud.model} @ {cfg.cloud.base_url}"
            if cfg.cloud.enabled
            else "disabled (router.mode=hybrid works without it)",
        )
    )

    # tools
    agent = JarvisAgent.create(cfg, EventBus())
    counts: Dict[str, int] = {}
    for spec in agent.registry.specs():
        counts[spec.category] = counts.get(spec.category, 0) + 1
    rows.append(("tools", True, ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))))
    for spec in agent.registry.specs():
        if spec.requires and not all(_importable(r) for r in spec.requires):
            rows.append((f"  -> optional", None, f"{spec.name} needs: pip install {' '.join(spec.requires)}"))

    # memory
    rows.append(("memory", bool(agent.memory), agent.memory.stats()["db_path"] if agent.memory else "disabled"))

    # voice
    voice = voice_status(cfg.voice)
    rows.append(
        (
            "wake word",
            voice["wake_word"]["available"],
            f"{voice['wake_word']['word']} via {voice['wake_word']['engine']}"
            + (f" — missing: {', '.join(voice['wake_word']['missing'])}" if voice["wake_word"]["missing"] else ""),
        )
    )
    rows.append(
        (
            "speech-to-text",
            voice["stt"]["available"],
            f"{voice['stt']['engine']} ({voice['stt']['model']}, lang={voice['stt']['language']})",
        )
    )
    rows.append(
        ("text-to-speech", voice["tts"]["available"], f"{voice['tts']['engine']} ({voice['tts']['voice']})")
    )
    rows.append(("microphone", voice["capture"]["available"], "sounddevice" if voice["capture"]["available"] else "pip install sounddevice"))

    for name, state, detail in rows:
        mark = {True: "[ OK ]", False: "[ -- ]", None: "[ .. ]"}[state]
        print(f"{mark} {name:<18} {detail}")

    print("\nHints")
    print(f"  • ollama pull {cfg.local.model}          # local brain (whisper/Piper models are separate)")
    print("  • pip install openwakeword sounddevice numpy   # wake word + microphone")
    print("  • pip install piper-tts                        # or drop piper.exe in ~/.jarvis/models")
    print("  • python -m jarvis serve                       # start the bridge, then open the HUD")
    return 0


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _starter_yaml() -> str:
    return """# ~/.jarvis/config.yaml  (all values are optional — these are the defaults)
persona:
  name: JARVIS
  user_title: sir
  language: auto          # auto | en | ar
  verbosity: short

local:                    # the local brain (Ollama)
  base_url: http://127.0.0.1:11434
  model: qwen3.5:4b
  vision_model: qwen2.5vl:7b

cloud:                    # optional tier for deep research / heavy reasoning
  enabled: false
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  api_key_env: OPENAI_API_KEY

router:
  mode: hybrid            # offline | local | cloud | hybrid

voice:
  wake_word: hey jarvis
  stt_engine: whisper_cpp  # whisper_cpp | faster_whisper | openai | none
  stt_model: base
  stt_language: ""         # "" = auto-detect (Arabic is supported)
  tts_engine: piper
  tts_voice: en_US-lessac-medium

memory:
  enabled: true
  db_path: ~/.jarvis/memory.db

security:
  mode: confirm-sensitive  # allow-all | confirm-sensitive | deny-sensitive
  allow_shell: false

tools:
  allowed_roots: ["~"]
  web_provider: duckduckgo

bridge:
  host: 127.0.0.1
  port: 8770
"""

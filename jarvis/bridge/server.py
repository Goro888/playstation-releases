"""FastAPI bridge between the JARVIS core and any UI (HUD, mobile, script).

The HUD is a thin client: it never touches Windows, files or the microphone
directly. It posts text here and receives a stream of events (status, tool
calls, permission requests, final message) over SSE.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..config import JarvisConfig
from ..core.agent import JarvisAgent
from ..events import Event, EventBus
from ..voice import VoicePipeline

log = logging.getLogger("jarvis.bridge")


class Runtime:
    """Holds the live objects the API talks to."""

    def __init__(self, cfg: JarvisConfig, agent: JarvisAgent, bus: EventBus) -> None:
        self.cfg = cfg
        self.agent = agent
        self.bus = bus
        self.voice = VoicePipeline(cfg.voice, bus)
        self._voice_task: Optional[asyncio.Task] = None
        self.started_at = time.time()

    # -- voice ------------------------------------------------------------
    async def start_voice(self, speak: bool = True, wake_word: bool = True) -> Dict[str, Any]:
        if self._voice_task and not self._voice_task.done():
            return {"running": True, "note": "already running"}

        async def handler(text: str) -> str:
            result = await self.agent.handle(text, session="voice")
            return result.text

        self._voice_task = self.voice.start(handler, speak=speak, wake_word=wake_word)
        return {"running": True, "speak": speak, "wake_word": wake_word}

    async def stop_voice(self) -> Dict[str, Any]:
        await self.voice.stop()
        self._voice_task = None
        return {"running": False}

    def voice_state(self) -> Dict[str, Any]:
        return {
            "running": bool(self._voice_task and not self._voice_task.done()),
            **self.voice.status(),
        }


def create_app(
    cfg: Optional[JarvisConfig] = None,
    agent: Optional[JarvisAgent] = None,
    bus: Optional[EventBus] = None,
    runtime: Optional[Runtime] = None,
) -> FastAPI:
    cfg = cfg or JarvisConfig.load()
    bus = bus or EventBus()
    agent = agent or JarvisAgent.create(cfg, bus)
    rt = runtime or Runtime(cfg, agent, bus)

    app = FastAPI(title="JARVIS bridge", version="1.0.0", description="Local-first AI operating assistant API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.bridge.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.runtime = rt
    app.state.cfg = cfg
    app.state.bus = bus
    app.state.agent = agent

    # ------------------------------------------------------------------ health
    @app.get("/api/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True, "uptime": round(time.time() - rt.started_at, 1), "version": "1.0.0"}

    @app.get("/api/status")
    async def status() -> Dict[str, Any]:
        data = await agent.status()
        data["voice_loop"] = rt.voice_state()
        data["uptime"] = round(time.time() - rt.started_at, 1)
        return data

    # ------------------------------------------------------------------- chat
    @app.post("/api/chat")
    async def chat(request: Request) -> Dict[str, Any]:
        body = await request.json() if await request.body() else {}
        message = str(body.get("message") or body.get("text") or "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        session = str(body.get("session") or "default")
        images = body.get("images") or []
        force = body.get("force")
        result = await agent.handle(message, session=session, images=images, force=force)
        return {"ok": True, "reply": result.text, **result.to_dict()}

    # ----------------------------------------------------------------- events
    @app.get("/api/events")
    async def events(request: Request, since: float = Query(0.0)) -> StreamingResponse:
        history = bus.history(limit=50, since=since)

        async def gen():
            queue = bus.subscribe()
            try:
                for item in history:
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event: Event = await asyncio.wait_for(queue.get(), timeout=15)
                    except (asyncio.TimeoutError, TimeoutError):
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {json.dumps(event.to_dict(), ensure_ascii=False)}\n\n"
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/history")
    async def history(limit: int = 50) -> Dict[str, Any]:
        return {"events": bus.history(limit=limit)}

    @app.get("/api/conversation")
    async def conversation(session: str = "default", limit: int = 40) -> Dict[str, Any]:
        if not agent.memory:
            return {"messages": []}
        return {"messages": agent.memory.history(limit=limit, session_id=session)}

    # ------------------------------------------------------------------ tools
    @app.get("/api/tools")
    async def tools() -> Dict[str, Any]:
        return {"tools": agent.registry.describe(system=platform.system().lower())}

    @app.post("/api/tools/call")
    async def call_tool(request: Request) -> Dict[str, Any]:
        body = await request.json() if await request.body() else {}
        name = str(body.get("name") or "").strip()
        args = body.get("args") or {}
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        result = await agent.run_tool(name, args, session="api")
        return result.to_dict()

    # ------------------------------------------------------------ permissions
    @app.get("/api/permissions")
    async def permissions() -> Dict[str, Any]:
        return {"pending": agent.permissions.pending()}

    @app.post("/api/permissions/{request_id}/approve")
    async def approve(request_id: str, remember: bool = Query(False)) -> Dict[str, Any]:
        ok = agent.permissions.resolve(request_id, True, remember=remember)
        if not ok:
            raise HTTPException(status_code=404, detail="unknown or expired request")
        return {"ok": True}

    @app.post("/api/permissions/{request_id}/deny")
    async def deny(request_id: str) -> Dict[str, Any]:
        ok = agent.permissions.resolve(request_id, False)
        if not ok:
            raise HTTPException(status_code=404, detail="unknown or expired request")
        return {"ok": True}

    @app.post("/api/permissions/approve-all")
    async def approve_all() -> Dict[str, Any]:
        return {"approved": agent.permissions.approve_all()}

    # ----------------------------------------------------------------- memory
    @app.get("/api/memory")
    async def memory_search(q: str = Query(""), limit: int = Query(10)) -> Dict[str, Any]:
        if not agent.memory:
            return {"facts": [], "stats": {"enabled": False}}
        facts = agent.memory.recall(q, limit=limit) if q else agent.memory.recent(limit)
        return {"facts": [f.to_dict() for f in facts], "stats": agent.memory.stats()}

    @app.post("/api/memory")
    async def memory_add(request: Request) -> Dict[str, Any]:
        if not agent.memory:
            raise HTTPException(status_code=400, detail="memory is disabled")
        body = await request.json() if await request.body() else {}
        content = str(body.get("content") or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="content is required")
        fact = agent.memory.remember(
            content,
            kind=str(body.get("kind") or "note"),
            subject=str(body.get("subject") or ""),
            tags=body.get("tags") or [],
            importance=int(body.get("importance") or 3),
        )
        bus.publish("memory_added", {"id": fact.id, "content": content})
        return {"ok": True, "fact": fact.to_dict()}

    @app.delete("/api/memory/{fact_id}")
    async def memory_delete(fact_id: int) -> Dict[str, Any]:
        if not agent.memory:
            raise HTTPException(status_code=400, detail="memory is disabled")
        return {"ok": agent.memory.forget(fact_id)}

    @app.get("/api/memory/stats")
    async def memory_stats() -> Dict[str, Any]:
        return agent.memory.stats() if agent.memory else {"enabled": False}

    @app.get("/api/tasks")
    async def tasks(status: str = Query("open")) -> Dict[str, Any]:
        if not agent.memory:
            return {"tasks": []}
        return {"tasks": agent.memory.list_tasks(status)}

    @app.post("/api/tasks")
    async def add_task(request: Request) -> Dict[str, Any]:
        if not agent.memory:
            raise HTTPException(status_code=400, detail="memory is disabled")
        body = await request.json() if await request.body() else {}
        title = str(body.get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="title is required")
        return {"ok": True, "task": agent.memory.add_task(title, str(body.get("notes") or ""))}

    @app.post("/api/tasks/{task_id}/done")
    async def complete_task(task_id: int) -> Dict[str, Any]:
        if not agent.memory:
            raise HTTPException(status_code=400, detail="memory is disabled")
        return {"ok": agent.memory.complete_task(task_id)}

    # ----------------------------------------------------------------- system
    @app.get("/api/system")
    async def system() -> Dict[str, Any]:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage(os.path.expanduser("~"))
        net = psutil.net_io_counters()
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.3),
            "per_cpu": psutil.cpu_percent(interval=None, percpu=True),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / 1073741824, 2),
            "ram_total_gb": round(vm.total / 1073741824, 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / 1073741824, 1),
            "processes": len(psutil.pids()),
            "net_sent_mb": round(net.bytes_sent / 1048576, 1) if net else 0,
            "net_recv_mb": round(net.bytes_recv / 1048576, 1) if net else 0,
            "uptime": round(time.time() - psutil.boot_time()),
            "platform": platform.platform(),
        }

    # ------------------------------------------------------------------ voice
    @app.post("/api/voice/start")
    async def voice_start(request: Request) -> Dict[str, Any]:
        body = await request.json() if await request.body() else {}
        return await rt.start_voice(speak=bool(body.get("speak", True)), wake_word=bool(body.get("wake_word", True)))

    @app.post("/api/voice/stop")
    async def voice_stop() -> Dict[str, Any]:
        return await rt.stop_voice()

    @app.get("/api/voice/status")
    async def voice_status() -> Dict[str, Any]:
        return rt.voice_state()

    @app.post("/api/voice/speak")
    async def voice_speak(request: Request) -> Dict[str, Any]:
        body = await request.json() if await request.body() else {}
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="text is required")
        result = await rt.voice.say(text)
        return result

    @app.post("/api/voice/listen")
    async def voice_listen(request: Request) -> Dict[str, Any]:
        """Record one utterance and transcribe it (no agent turn)."""
        body = await request.json() if await request.body() else {}
        try:
            text = await rt.voice.listen_once()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reply = None
        if body.get("respond", True) and text:
            result = await agent.handle(text, session="voice")
            reply = result.text
            if body.get("speak", True):
                await rt.voice.say(reply)
        return {"text": text, "reply": reply}

    @app.get("/api/audio")
    async def audio(path: str = Query("")) -> Any:
        """Stream a WAV produced by the TTS engine (guarded to the audio dir)."""
        if not path:
            raise HTTPException(status_code=400, detail="path is required")
        root = Path(os.path.expanduser(cfg.voice.models_dir)).parent.resolve()
        target = Path(os.path.expanduser(path)).resolve()
        if not str(target).lower().endswith(".wav") or root not in target.parents:
            raise HTTPException(status_code=403, detail="refusing to serve that file")
        if not target.exists():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(target, media_type="audio/wav")

    # --------------------------------------------------------------- config
    @app.get("/api/config")
    async def get_config() -> Dict[str, Any]:
        """Return a redacted view of the running configuration."""
        data = cfg.to_dict()
        data["cloud"].pop("base_url", None)
        return data

    # ------------------------------------------------------------------- UI
    ui_dir = Path(cfg.bridge.ui_dir)
    if cfg.bridge.serve_ui and ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="hud")

        @app.get("/hud")
        async def hud_index() -> Any:
            return FileResponse(ui_dir / "index.html")

    return app

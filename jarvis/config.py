"""Configuration loading for JARVIS.

Configuration is layered (each layer overrides the previous one):

1. built-in defaults (below)
2. ``config/jarvis.yaml`` next to the repo, or ``~/.jarvis/config.yaml``
3. ``JARVIS_*`` environment variables
4. explicit CLI flags

Nothing here is mandatory — the app boots with zero configuration and falls
back to the offline brain.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - pyyaml is a hard requirement
    yaml = None


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
@dataclass
class PersonaConfig:
    name: str = "JARVIS"
    user_title: str = "sir"
    style: str = "calm, precise, concise, composed; light dry wit; never overly cheerful"
    language: str = "auto"  # auto | en | ar
    verbosity: str = "short"  # short | normal | detailed


@dataclass
class LocalConfig:
    """Local inference (Ollama by default; any OpenAI-compatible server works)."""

    backend: str = "ollama"  # ollama | openai_compatible
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:4b"
    vision_model: str = "qwen2.5vl:7b"
    embed_model: str = "nomic-embed-text"
    temperature: float = 0.3
    num_ctx: int = 8192
    keep_alive: str = "10m"
    timeout: float = 180.0
    fallback_models: List[str] = field(
        default_factory=lambda: ["qwen2.5:7b-instruct", "llama3.2:3b", "qwen2.5:3b"]
    )


@dataclass
class CloudConfig:
    """Optional cloud tier for deep research / heavy reasoning / best voice."""

    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"
    timeout: float = 120.0
    max_tokens: int = 2048


@dataclass
class RouterConfig:
    """Decides local vs cloud per request (the hybrid design)."""

    mode: str = "hybrid"  # offline | local | cloud | hybrid
    cloud_min_chars: int = 600
    cloud_keywords: List[str] = field(
        default_factory=lambda: [
            "research",
            "deep dive",
            "deep research",
            "compare",
            "analyze",
            "write a report",
            "business plan",
            "long document",
            "ابحث",
            "بحث",
            "تقرير",
            "حلل",
            "قارن",
            "لخّص",
            "لخص هذه الوثيقة",
        ]
    )
    allow_vision_cloud: bool = True
    force_cloud_prefix: str = "/cloud"
    force_local_prefix: str = "/local"


@dataclass
class VoiceConfig:
    """Wake word -> STT -> TTS. Every engine is optional."""

    enabled: bool = True
    # wake word
    wake_word: str = "hey jarvis"
    wake_engine: str = "openwakeword"  # openwakeword | none
    wake_threshold: float = 0.5
    wake_model_path: str = ""  # custom .onnx; empty = built-in hey_jarvis
    # speech to text
    stt_engine: str = "whisper_cpp"  # whisper_cpp | faster_whisper | openai | none
    stt_model: str = "base"  # whisper.cpp model name OR faster-whisper id
    stt_language: str = ""  # "" = auto-detect, or "ar", "en", ...
    stt_binary: str = "whisper-cli"  # main | whisper-cli | whisper.cpp builds
    # text to speech
    tts_engine: str = "piper"  # piper | pyttsx3 | none
    tts_voice: str = "en_US-lessac-medium"
    piper_binary: str = "piper"
    piper_model_dir: str = "~/.jarvis/models/piper"
    piper_length_scale: float = 1.0
    piper_speaker: int = 0
    # audio capture
    models_dir: str = "~/.jarvis/models"
    sample_rate: int = 16000
    channels: int = 1
    listen_timeout: float = 10.0
    phrase_max_seconds: float = 25.0
    silence_rms: float = 0.012
    silence_seconds: float = 1.0
    device: str = ""  # sounddevice device id/name; empty = default


@dataclass
class MemoryConfig:
    enabled: bool = True
    db_path: str = "~/.jarvis/memory.db"
    store_conversations: bool = True
    history_limit: int = 40
    recall_limit: int = 6
    embeddings: bool = False
    embed_model: str = "nomic-embed-text"


@dataclass
class SecurityConfig:
    """The permission layer — the LLM never touches Windows directly."""

    mode: str = "confirm-sensitive"  # allow-all | confirm-sensitive | deny-sensitive
    auto_approve: List[str] = field(default_factory=list)
    require_confirm: List[str] = field(default_factory=list)
    denied: List[str] = field(default_factory=list)
    allow_shell: bool = False
    confirm_timeout: float = 120.0
    max_output_chars: int = 4000


@dataclass
class ToolsConfig:
    enabled: List[str] = field(
        default_factory=lambda: ["system", "files", "clipboard", "ui", "screen", "web", "memory", "misc"]
    )
    # web
    web_provider: str = "duckduckgo"  # duckduckgo | brave | searxng
    brave_api_key_env: str = "BRAVE_API_KEY"
    searxng_url: str = "http://127.0.0.1:8080"
    search_results: int = 5
    fetch_max_chars: int = 6000
    # files / screen
    screenshot_dir: str = "~/.jarvis/screenshots"
    allowed_roots: List[str] = field(default_factory=lambda: ["~"])
    app_aliases: Dict[str, str] = field(
        default_factory=lambda: {
            "chrome": "chrome",
            "google chrome": "chrome",
            "firefox": "firefox",
            "edge": "msedge",
            "vscode": "code",
            "visual studio code": "code",
            "visual studio": "devenv",
            "notepad": "notepad",
            "calculator": "calc",
            "calc": "calc",
            "terminal": "wt",
            "powershell": "powershell",
            "explorer": "explorer",
            "file explorer": "explorer",
            "spotify": "spotify",
            "discord": "discord",
            "whatsapp": "whatsapp",
            "telegram": "telegram",
            "obs": "obs64",
            "steam": "steam",
        }
    )


@dataclass
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8770
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    serve_ui: bool = True
    ui_dir: str = "hud/dist"


@dataclass
class AgentConfig:
    max_steps: int = 8
    planning: bool = True
    max_tool_output_chars: int = 3000


@dataclass
class JarvisConfig:
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    cloud: CloudConfig = field(default_factory=CloudConfig)
    router: RouterConfig = field(default_factory=RouterConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    log_level: str = "INFO"
    config_path: str = ""

    # -- loading ----------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None, **overrides: Any) -> "JarvisConfig":
        data: Dict[str, Any] = {}
        chosen = None
        candidates = [Path(path)] if path else [Path("config/jarvis.yaml"), Path.home() / ".jarvis" / "config.yaml"]
        for candidate in candidates:
            p = Path(candidate).expanduser()
            if p.is_file():
                chosen = p
                break
        if chosen is not None and yaml is not None:
            try:
                data = yaml.safe_load(chosen.read_text(encoding="utf-8")) or {}
            except Exception:  # pragma: no cover - broken yaml
                data = {}
        elif chosen is not None and yaml is None:  # pragma: no cover
            data = {}

        cfg = cls.from_dict(data)
        cfg.config_path = str(chosen) if chosen else ""
        cfg.apply_env()
        if overrides:
            cfg = cls.from_dict(_deep_merge(asdict(cfg), overrides))
        return cfg

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "JarvisConfig":
        data = data or {}
        return cls(
            persona=_build(PersonaConfig, data.get("persona")),
            local=_build(LocalConfig, data.get("local")),
            cloud=_build(CloudConfig, data.get("cloud")),
            router=_build(RouterConfig, data.get("router")),
            voice=_build(VoiceConfig, data.get("voice")),
            memory=_build(MemoryConfig, data.get("memory")),
            security=_build(SecurityConfig, data.get("security")),
            tools=_build(ToolsConfig, data.get("tools")),
            bridge=_build(BridgeConfig, data.get("bridge")),
            agent=_build(AgentConfig, data.get("agent")),
            log_level=data.get("log_level", "INFO"),
        )

    def apply_env(self) -> None:
        """Apply ``JARVIS_*`` / standard env overrides."""
        env = os.environ
        if env.get("JARVIS_LOG_LEVEL"):
            self.log_level = env["JARVIS_LOG_LEVEL"]
        if env.get("JARVIS_HOME"):
            home = Path(env["JARVIS_HOME"]).expanduser()
            self.memory.db_path = str(home / "memory.db")
            self.voice.models_dir = str(home / "models")
            self.tools.screenshot_dir = str(home / "screenshots")
        if env.get("JARVIS_HOST"):
            self.bridge.host = env["JARVIS_HOST"]
        if env.get("JARVIS_PORT"):
            self.bridge.port = int(env["JARVIS_PORT"])
        if env.get("OLLAMA_HOST"):
            self.local.base_url = _normalize_base_url(env["OLLAMA_HOST"])
        if env.get("JARVIS_MODEL"):
            self.local.model = env["JARVIS_MODEL"]
        if env.get("JARVIS_MODE"):
            self.router.mode = env["JARVIS_MODE"]
        if env.get("JARVIS_CLOUD") in ("1", "true", "yes", "on"):
            self.cloud.enabled = True
        if env.get("JARVIS_CLOUD_BASE_URL"):
            self.cloud.base_url = env["JARVIS_CLOUD_BASE_URL"]
        if env.get("JARVIS_CLOUD_MODEL"):
            self.cloud.model = env["JARVIS_CLOUD_MODEL"]

    # -- helpers ----------------------------------------------------------
    @property
    def home(self) -> Path:
        base = Path(
            os.environ.get("JARVIS_HOME", str(Path(self.memory.db_path).expanduser().parent))
        ).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return base

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: str | os.PathLike[str]) -> Path:
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML is required to write config files")
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        data.pop("config_path", None)
        p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return p


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _build(cls, data: Any):
    if data is None:
        return cls()
    if isinstance(data, cls):
        return data
    if not isinstance(data, dict):
        return cls()
    allowed = set(cls.__dataclass_fields__)
    return cls(**{k: v for k, v in data.items() if k in allowed})


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any] | None) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _normalize_base_url(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return raw
    if not raw.startswith("http"):
        raw = f"http://{raw}"
    return raw.rstrip("/")

"""Cross-platform helpers for the tool layer.

Windows is the target platform, so every function has a Windows-first
implementation (PowerShell + UI Automation) and a POSIX fallback so the whole
stack can still be developed, demoed and tested on Linux/macOS.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

IS_WINDOWS = os.name == "nt" or platform.system().lower() == "windows"
IS_LINUX = platform.system().lower() == "linux"
IS_MAC = platform.system().lower() == "darwin"


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------
def run(cmd: List[str], timeout: float = 20.0, *, text: bool = True) -> Tuple[int, str, str]:
    """Run a command without a shell. Returns ``(code, stdout, stderr)``."""
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=text,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS and hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"


def ps_quote(value: str) -> str:
    """Escape a string for use inside PowerShell single quotes."""
    return "'" + str(value).replace("'", "''") + "'"


def powershell(script: str, timeout: float = 25.0) -> Tuple[int, str, str]:
    exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    return run([exe, "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def shell(cmd: str, timeout: float = 30.0) -> Tuple[int, str, str]:
    if IS_WINDOWS:
        return powershell(cmd, timeout)
    return run(["/bin/sh", "-c", cmd], timeout)


# --------------------------------------------------------------------------
# launching applications
# --------------------------------------------------------------------------
_WIN_SEARCH_DIRS = (
    "%ProgramFiles%",
    "%ProgramFiles(x86)%",
    "%LocalAppData%\\Programs",
    "%LocalAppData%",
    "%AppData%",
    "%SystemRoot%\\System32",
)
_LINUX_CANDIDATES = {
    "chrome": ["google-chrome", "chromium", "chromium-browser"],
    "google-chrome": ["google-chrome", "chromium"],
    "code": ["code"],
    "firefox": ["firefox"],
}


def resolve_executable(target: str, aliases: Dict[str, str] | None = None) -> Optional[str]:
    """Resolve a friendly app name to something the OS can execute."""
    target = (target or "").strip().strip('"')
    if not target:
        return None
    aliases = aliases or {}
    key = target.lower()
    candidate = aliases.get(key, target)

    # already a path or explicit file
    if any(sep in candidate for sep in ("/", "\\")) or candidate.lower().endswith(
        (".exe", ".lnk", ".msc", ".bat", ".cmd", ".app", ".desktop")
    ):
        expanded = os.path.expandvars(os.path.expanduser(candidate))
        if os.path.exists(expanded):
            return expanded
        return candidate

    if not IS_WINDOWS:
        for name in _LINUX_CANDIDATES.get(candidate.lower(), [candidate]):
            found = shutil.which(name)
            if found:
                return found
        return shutil.which(candidate)

    # Windows: WHERE first (picks up PATH + App Paths registered apps)
    code, out, _ = run(["where.exe", candidate], timeout=6)
    if code == 0 and out:
        return out.splitlines()[0].strip()

    # then a quick scan of the usual install locations
    stem = candidate.lower()
    if not stem.endswith(".exe"):
        stem += ".exe"
    for raw_dir in _WIN_SEARCH_DIRS:
        base = os.path.expandvars(raw_dir)
        if not base or not os.path.isdir(base):
            continue
        try:
            for root, _dirs, files in os.walk(base):
                depth = root[len(base) :].count(os.sep)
                if depth > 2:
                    continue
                for f in files:
                    if f.lower() == stem:
                        return os.path.join(root, f)
        except (OSError, PermissionError):  # pragma: no cover
            continue
    return None


def launch(target: str, aliases: Dict[str, str] | None = None, args: str = "") -> Dict[str, Any]:
    """Start an application or open a file/URL. Returns a status dict."""
    exe = resolve_executable(target, aliases)
    if exe:
        try:
            if IS_WINDOWS:
                os.startfile(exe)  # type: ignore[attr-defined]  # honours file associations
                kind = "startfile"
            else:
                argv = [exe] + ([a for a in args.split() if a] if args else [])
                subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                kind = "popen"
            return {"ok": True, "target": target, "resolved": exe, "method": kind}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "target": target, "resolved": exe, "error": str(exc)}

    # fall back to the shell verb (handles URLs, Store apps, AppX aliases)
    if IS_WINDOWS:
        script = f"Start-Process -FilePath {ps_quote(target)}"
        if args:
            script += f" -ArgumentList {ps_quote(args)}"
        code, out, err = powershell(script)
    else:
        opener = shutil.which("xdg-open") or shutil.which("open")
        if not opener:
            return {"ok": False, "target": target, "error": "no application found and no xdg-open/open helper"}
        code, out, err = run([opener, target] + ([args] if args else []))

    if code == 0:
        return {"ok": True, "target": target, "resolved": target, "method": "shell"}
    return {"ok": False, "target": target, "error": err or out or f"exit code {code}"}


def terminate(target: str) -> Dict[str, Any]:
    """Close an application by name."""
    name = (target or "").strip()
    if not name:
        return {"ok": False, "error": "no application name given"}
    if IS_WINDOWS:
        proc = name if name.lower().endswith(".exe") else f"{name}*"
        code, out, err = powershell(
            f"$p = Get-Process -Name {ps_quote(proc.replace('*',''))} -ErrorAction SilentlyContinue; "
            f"if ($p) {{ $p | Stop-Process -Force; \"stopped {name}\" }} else {{ \"not running\" }}"
        )
        ok = code == 0 and "not running" not in out.lower()
        return {"ok": ok, "output": out or err, "target": name}
    code, out, err = run(["pkill", "-f", name])
    if code == 0:
        return {"ok": True, "output": f"stopped {name}", "target": name}
    return {"ok": False, "output": err or f"no process matched '{name}'", "target": name}


# --------------------------------------------------------------------------
# window / UI automation
# --------------------------------------------------------------------------
def _ui_backend() -> Tuple[Optional[str], Any]:
    try:
        import uiautomation as auto  # type: ignore

        return "uiautomation", auto
    except Exception:  # noqa: BLE001
        pass
    try:
        from pywinauto import Desktop  # type: ignore

        return "pywinauto", Desktop
    except Exception:  # noqa: BLE001
        pass
    return None, None


def list_windows() -> Dict[str, Any]:
    """List visible windows with titles (Windows via UI Automation / PowerShell)."""
    if not IS_WINDOWS:
        code, out, _ = run(["sh", "-c", "wmctrl -l 2>/dev/null || echo ''"])
        rows = []
        for line in (out or "").splitlines():
            parts = line.split(None, 3)
            if len(parts) >= 4:
                rows.append({"handle": parts[0], "title": parts[3], "app": parts[2]})
        if rows:
            return {"ok": True, "backend": "wmctrl", "windows": rows}
        return {"ok": False, "error": "window listing requires Windows (UI Automation) or wmctrl on Linux"}

    kind, mod = _ui_backend()
    if kind == "uiautomation":
        try:
            wins = []
            for w in mod.GetRootControl().GetChildren():
                if not w.Name:
                    continue
                wins.append({"title": w.Name, "class": w.ClassName or "", "handle": hex(w.NativeWindowHandle or 0)})
            return {"ok": True, "backend": "uiautomation", "windows": wins[:60]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"uiautomation failed: {exc}"}
    if kind == "pywinauto":
        try:
            wins = [
                {"title": w.window_text(), "app": getattr(w.element_info, "name", "")}
                for w in mod(backend="uia").windows()
                if w.window_text()
            ]
            return {"ok": True, "backend": "pywinauto", "windows": wins[:60]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"pywinauto failed: {exc}"}

    # PowerShell fallback — no extra packages needed
    script = (
        "Get-Process | Where-Object { $_.MainWindowTitle -ne '' } | "
        "Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json -Compress"
    )
    code, out, err = powershell(script)
    if code != 0 or not out:
        return {"ok": False, "error": err or "could not enumerate windows"}
    try:
        import json

        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        windows = [
            {"title": d.get("MainWindowTitle", ""), "app": d.get("ProcessName", ""), "pid": d.get("Id")}
            for d in data
            if d.get("MainWindowTitle")
        ]
        return {"ok": True, "backend": "powershell", "windows": windows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"could not parse window list: {exc}"}


def focus_window(title: str) -> Dict[str, Any]:
    if not IS_WINDOWS:
        code, out, err = run(["wmctrl", "-a", title])
        return {"ok": code == 0, "output": out or err, "title": title, "backend": "wmctrl"}
    kind, mod = _ui_backend()
    if kind == "uiautomation":
        try:
            win = mod.WindowControl(searchDepth=2, RegexName=f".*{title}.*")
            if not win.Exists(maxSearchSeconds=3):
                return {"ok": False, "error": f"no window matching '{title}'", "title": title}
            win.SetFocus()
            return {"ok": True, "output": f"focused '{win.Name}'", "title": win.Name, "backend": "uiautomation"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "title": title}
    script = (
        f"$w = (New-Object -ComObject WScript.Shell); "
        f"$proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{title}*' }} | Select-Object -First 1; "
        f"if ($proc) {{ $w.AppActivate($proc.Id); \"activated: \" + $proc.MainWindowTitle }} else {{ 'not found' }}"
    )
    code, out, err = powershell(script)
    ok = code == 0 and "not found" not in (out or "").lower()
    return {"ok": ok, "output": out or err, "title": title, "backend": "powershell"}


def click_control(window_title: str, control: str) -> Dict[str, Any]:
    """Click a named control inside a window (Windows UI Automation)."""
    if not IS_WINDOWS:
        return {"ok": False, "error": "click_control requires Windows UI Automation"}
    kind, mod = _ui_backend()
    if kind != "uiautomation":
        return {
            "ok": False,
            "error": "install `pip install uiautomation` (or pywinauto) to control individual UI elements",
            "window": window_title,
            "control": control,
        }
    try:
        win = mod.WindowControl(searchDepth=2, RegexName=f".*{window_title}.*")
        if not win.Exists(maxSearchSeconds=3):
            return {"ok": False, "error": f"no window matching '{window_title}'"}
        target = None
        for depth in (4, 8, 12):
            target = win.Control(searchDepth=depth, RegexName=f".*{control}.*")
            if target.Exists(maxSearchSeconds=1):
                break
            target = None
        if target is None:
            return {"ok": False, "error": f"no control matching '{control}' inside '{window_title}'"}
        target.Click()
        return {"ok": True, "output": f"clicked '{control}' in '{window_title}'", "backend": "uiautomation"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def type_text(text: str) -> Dict[str, Any]:
    """Type into the focused window."""
    if not IS_WINDOWS:
        return {"ok": False, "error": "type_text is Windows-only (uses UI Automation / SendKeys)"}
    kind, mod = _ui_backend()
    if kind == "uiautomation":
        try:
            mod.SendKeys(text)
            return {"ok": True, "output": f"typed {len(text)} characters", "backend": "uiautomation"}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    escaped = text.replace("^", "^{}").replace("+", "{+}").replace("%", "{%}").replace("(", "{(}").replace(")", "{)}")
    script = (
        f"$ws = New-Object -ComObject WScript.Shell; Start-Sleep -Milliseconds 200; "
        f"$ws.SendKeys({ps_quote(escaped)})"
    )
    code, out, err = powershell(script)
    return {"ok": code == 0, "output": out or err or f"typed {len(text)} characters", "backend": "powershell"}


# --------------------------------------------------------------------------
# clipboard
# --------------------------------------------------------------------------
def clipboard_get() -> Dict[str, Any]:
    if IS_WINDOWS:
        code, out, err = powershell("Get-Clipboard -Raw")
        return {"ok": code == 0, "text": out, "error": None if code == 0 else err}
    try:
        import pyperclip  # type: ignore

        return {"ok": True, "text": pyperclip.paste()}
    except Exception:  # noqa: BLE001
        pass
    for cmd in (["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
        code, out, err = run(cmd, timeout=5)
        if code == 0:
            return {"ok": True, "text": out}
    return {"ok": False, "error": "clipboard access needs PowerShell (Windows), pyperclip, xclip or xsel"}


def clipboard_set(text: str) -> Dict[str, Any]:
    if IS_WINDOWS:
        script = f"Set-Clipboard -Value {ps_quote(text)}"
        code, out, err = powershell(script)
        return {"ok": code == 0, "error": None if code == 0 else err, "chars": len(text)}
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return {"ok": True, "chars": len(text)}
    except Exception:  # noqa: BLE001
        pass
    for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        try:
            p = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=5)
            if p.returncode == 0:
                return {"ok": True, "chars": len(text)}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return {"ok": False, "error": "clipboard write needs PowerShell (Windows), pyperclip, xclip or xsel"}


# --------------------------------------------------------------------------
# screenshots
# --------------------------------------------------------------------------
def screenshot(path: str) -> Dict[str, Any]:
    """Capture the whole virtual screen. Uses mss when available."""
    out = Path(os.path.expanduser(path))
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import mss  # type: ignore

        with mss.mss() as sct:
            monitor = sct.monitors[0]
            sct.shot(mon=0, output=str(out))
        return {"ok": True, "path": str(out)}
    except Exception as exc:  # noqa: BLE001
        pass
    try:
        from PIL import ImageGrab  # type: ignore

        ImageGrab.grab(all_screens=True).save(str(out))
        return {"ok": True, "path": str(out)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"screenshot failed: {exc}"}


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------
def now_info() -> Dict[str, Any]:
    import datetime

    now = datetime.datetime.now()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%A, %d %B %Y"),
        "timezone": time.tzname[0] if time.tzname else "",
        "weekday": now.strftime("%A"),
    }

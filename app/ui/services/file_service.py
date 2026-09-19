"""File Service — OS file/clipboard helpers extracted from bridge.py (R3).

Pure data in/out (dicts), no Qt, no bridge: the panel passes an optional
`log` callback (`Bridge._log`) so user-facing messages stay byte-identical.
Qt clipboard stays in the panel (services never touch Qt); only the
subprocess fallback chain lives here.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple


def _resolve_reveal_target(path_str: str) -> Tuple[Optional[Path], Optional[str]]:
    """Existing path (or its existing parent); (None, error) when neither."""
    p = Path(path_str)
    if p.exists():
        return p, None
    if p.parent.exists():
        return p.parent, None
    return None, f"Path does not exist: {path_str}"


def _reveal_windows(p: Path) -> None:
    if p.is_file():
        subprocess.Popen(f'explorer /select,"{p}"')
    else:
        os.startfile(str(p))  # type: ignore


def _reveal_mac(p: Path) -> None:
    if p.is_file():
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["open", str(p)])


def _reveal_linux(p: Path) -> None:
    if p.is_file():
        subprocess.Popen(["xdg-open", str(p.parent)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def _reveal_on_system(p: Path, system: str) -> None:
    """Open path with the OS explorer (raises on failure)."""
    if system == "Windows":
        _reveal_windows(p)
    elif system == "Darwin":
        _reveal_mac(p)
    else:
        _reveal_linux(p)


def reveal_path(path_str: str, log: Optional[Callable] = None) -> Dict:
    """Open file/folder in the OS explorer; mirrors bridge.reveal_in_explorer."""
    try:
        p, err = _resolve_reveal_target(path_str)
        if err:
            return {"ok": False, "error": err}
        try:
            _reveal_on_system(p, platform.system())
            if log:
                log(f"📁 Revealed in Explorer: {path_str}", "info")
            return {"ok": True, "path": str(p)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _copy_windows(text: str, log: Optional[Callable]) -> Dict:
    """clip, else powershell Set-Clipboard (spaces/Unicode-safe)."""
    path_str = text
    try:
        subprocess.run("clip", input=path_str.encode("utf-8"), check=True, shell=True)
        if log:
            log(f"📋 Copied via clip: {path_str}", "info")
        return {"ok": True, "path": path_str, "fallback": "clip"}
    except Exception:
        try:
            ps_escaped = path_str.replace("'", "''")
            ps_cmd = f"Set-Clipboard -Value '{ps_escaped}'"
            subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            if log:
                log(f"📋 Copied via powershell: {path_str}", "info")
            return {"ok": True, "path": path_str, "fallback": "powershell"}
        except Exception as e_ps:
            return {"ok": False, "error": f"clip/powershell failed {e_ps}", "path": path_str}


def _copy_mac(text: str, log: Optional[Callable]) -> Dict:
    """pbcopy (raises to caller on failure, as the original did)."""
    subprocess.run("pbcopy", input=text.encode("utf-8"), check=True)
    if log:
        log(f"📋 Copied via pbcopy: {text}", "info")
    return {"ok": True, "path": text, "fallback": "pbcopy"}


def _copy_linux(text: str, log: Optional[Callable]) -> Dict:
    """xclip, else xsel."""
    try:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True)
        if log:
            log(f"📋 Copied via xclip: {text}", "info")
        return {"ok": True, "path": text, "fallback": "xclip"}
    except Exception:
        try:
            subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=True)
            if log:
                log(f"📋 Copied via xsel: {text}", "info")
            return {"ok": True, "path": text, "fallback": "xsel"}
        except Exception as e_x:
            return {"ok": False, "error": f"xclip/xsel failed {e_x}", "path": text}


def copy_text_to_clipboard(text: str, log: Optional[Callable] = None) -> Dict:
    """Subprocess clipboard chain (Qt attempt stays in the panel)."""
    system = platform.system()
    if system == "Windows":
        return _copy_windows(text, log)
    if system == "Darwin":
        return _copy_mac(text, log)
    return _copy_linux(text, log)

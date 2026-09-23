"""Browser registry — Chrome, the one browser with a debug endpoint (2026-09-22).

This module is the ONE place that knows the debuggable browser's binaries,
flags, default profile dir and launch command; the Settings panel renders
whatever the registry row says (data-driven, no second vocabulary in JS).

History (I-62): Firefox and Edge rows lived here while the app tried DevTools
RDP / BiDi / attached sockets. Those approaches are deleted — a normal Firefox
has no debug channel worth driving, and Edge was a Chrome twin nobody asked
for. Firefox automation now runs through the Ui.Vision RPA extension
(`app/browser/uivision/`, window "Firefox auto with Extension"): native OS
input in a visible browser, no debugger port at all. Chrome keeps exactly what
it always had — CDP on `--remote-debugging-port`.

`ScanNote`/`scan_line` are the Settings scan vocabulary: what one Refresh asks
and why an endpoint could not answer.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

REMOTE_DEBUGGING_PORT = "remote-debugging-port"

PROTOCOL_CDP = "cdp"

# What the debug endpoint can do — one browser, one honest list (D-3).
CAPABILITIES: frozenset = frozenset({"tabs", "evaluate", "navigate", "screenshot",
                                     "set_files", "input", "dom"})


@dataclass(frozen=True)
class BrowserProfile:
    """One browser: identity, endpoint offset, profile dir, binaries, flags."""

    id: str
    label: str
    protocol: str
    port_offset: int
    dir_flag: str
    data_dir_default: str
    extra_args_default: str = ""
    executables: Dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def binary(self, os_name: str) -> str:
        """Executable path/name for an OS key (`windows` / `linux` / `macos`)."""
        return self.executables.get(os_name, self.executables.get("linux", self.id))


PROFILES: Tuple[BrowserProfile, ...] = (
    BrowserProfile(
        id="chrome", label="Chrome (Chromium)", protocol=PROTOCOL_CDP, port_offset=0,
        dir_flag="--user-data-dir", data_dir_default="C:\\arena-images-chrome",
        extra_args_default="",
        executables={
            "windows": '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"',
            "linux": "google-chrome",
            "macos": '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"',
        },
        notes="Full automation (CDP): tabs, JS, screenshots, file attach, input.",
    ),
)

OS_KEYS: Tuple[str, ...] = ("windows", "linux", "macos")


def current_os() -> str:
    """`windows` / `linux` / `macos` — the key the panel asks the registry for."""
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def profile_of(browser_id: str) -> Optional[BrowserProfile]:
    """The profile row for an id (None when unknown — callers report, never guess)."""
    want = (browser_id or "").strip().lower()
    for p in PROFILES:
        if p.id == want:
            return p
    return None


def profile_ids() -> List[str]:
    """Every registered browser id, registry order."""
    return [p.id for p in PROFILES]


def default_profile() -> BrowserProfile:
    """The browser a fresh install uses (Chrome — the app's only one)."""
    return PROFILES[0]


def resolve_port(base_port, profile: BrowserProfile, override=None) -> int:
    """Endpoint port: the per-browser override, else the shared base + the offset.

    The shared `cdp_port` setting is the BASE and each registry row derives its
    own endpoint (Chrome +0). The panel always shows the resolved number, so the
    setting stays predictable.
    """
    try:
        want = int(override or 0)
        if 1 <= want <= 65535:
            return want
    except Exception:
        pass
    try:
        base = int(base_port)
    except Exception:
        base = 9222
    base = base if 1 <= base <= 65535 else 9222
    return base + profile.port_offset if base + profile.port_offset <= 65535 else base


def endpoint(port, data_dir: str, extra_args: str = "", url: str = "") -> dict:
    """What a launch command is built from: endpoint port, profile dir, args, URL."""
    return {"port": port, "data_dir": data_dir, "extra_args": extra_args, "url": url}


def debug_arg(profile: BrowserProfile, port) -> str:
    """The flag that opens the browser's debug channel (`--remote-debugging-port=N`)."""
    return f"--{REMOTE_DEBUGGING_PORT}={int(port)}"


def build_command(profile: BrowserProfile, os_name: str, target: dict) -> str:
    """One launch command: binary + debug-channel flag + profile dir + args (+ URL)."""
    parts = [profile.binary(os_name), debug_arg(profile, target["port"])]
    data_dir = (target.get("data_dir") or "").strip()
    if data_dir:                          # empty = the browser's own profile (D-1, round 10)
        parts.append(f'{profile.dir_flag}="{data_dir}"')
    extra = target.get("extra_args") or profile.extra_args_default
    if (extra or "").strip():
        parts.append(extra.strip())
    if target.get("url"):
        parts.append(target["url"])
    return " ".join(parts)


def launch_commands(profile: BrowserProfile, target: dict) -> Dict[str, str]:
    """Per-OS commands for one browser (`windows`/`linux`/`macos` + `*_with_url`)."""
    cmds = {os_name: build_command(profile, os_name, target) for os_name in OS_KEYS}
    with_url = {**target, "url": target.get("url") or "https://arena.ai"}
    for os_name in OS_KEYS:
        cmds[f"{os_name}_with_url"] = build_command(profile, os_name, with_url)
    return cmds


def capabilities(profile: BrowserProfile) -> List[str]:
    """Sorted capability names of the protocol this browser speaks."""
    return sorted(CAPABILITIES if profile.protocol == PROTOCOL_CDP else frozenset())


def default_data_dir(browser_id: str) -> str:
    """Configured default profile dir of a browser ('' for an unknown id)."""
    profile = profile_of(browser_id)
    return profile.data_dir_default if profile else ""


@dataclass
class ScanNote:
    """One endpoint that could not be listed: where it is and what to do."""

    browser: str
    host: str
    port: int
    reason: str
    protocol: str = ""

    @property
    def line(self) -> str:
        """The one line a scan logs for this endpoint (D-6)."""
        return f"· {self.browser} on {self.host}:{self.port} — {self.reason}"


def scan_line(rows: List[Dict]) -> str:
    """The Settings line: every endpoint one Refresh asks, and which are off (D-9)."""
    parts = []
    for row in rows:
        where = f"{row.get('host', '')}:{row['port']}".lstrip(":")
        state = f"{row['id']} {where} ({str(row['protocol']).upper()})"
        parts.append(state if row.get("enabled") else f"{row['id']} — off")
    return "Scanning: " + " · ".join(parts)

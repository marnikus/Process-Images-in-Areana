"""Browser registry — more than one browser, one data-driven table (2026-09-21).

Owner request: Firefox next to Chrome, same host/port setting, per-browser data
dir + launch command, other browsers later. This module is the ONE place that
knows a browser's binaries, flags, default profile dir, protocol **and the flag
that opens its debug channel**; adding a browser later is one row here, not a
new code path.

Protocol reality (measured 2026-09-21, round 8):
* Chrome/Edge/Chromium speak CDP (`GET /json/list`, one socket per tab).
* Firefox is attached over the legacy **DevTools RDP** socket that
  `--start-debugger-server` opens. Its Remote Agent (`--remote-debugging-port`,
  WebDriver BiDi and the removed CDP) sets `navigator.webdriver = true` for the
  whole browser session (Firefox bug 1719505) — that is exactly the automation
  signal the stealth requirement forbids, so this registry never generates that
  flag for Firefox (pinned by a test).
`detect_protocol` in `endpoints.py` decides per endpoint (CDP → RDP → BiDi);
`capabilities` states what each protocol can do, so a missing operation can
refuse by name instead of timing out.

RED at `bce5a01`: this module did not exist.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import protocols as PROTOCOLS

REMOTE_DEBUGGING_PORT = "remote-debugging-port"
START_DEBUGGER_SERVER = "start-debugger-server"

PROTOCOL_CDP = PROTOCOLS.PROTOCOL_CDP
PROTOCOL_RDP = PROTOCOLS.PROTOCOL_RDP
PROTOCOL_BIDI = PROTOCOLS.PROTOCOL_BIDI

# What each protocol can do today (the one gate a CDP-only op asks, D-3).
CAPABILITIES: Dict[str, frozenset] = {
    PROTOCOL_CDP: frozenset({"tabs", "evaluate", "navigate", "screenshot",
                             "set_files", "input", "dom"}),
    PROTOCOL_RDP: frozenset({"tabs", "evaluate", "click"}),
    PROTOCOL_BIDI: frozenset({"tabs", "evaluate", "navigate"}),
}


@dataclass(frozen=True)
class BrowserProfile:
    """One browser: identity, endpoint offset, profile dir, binaries, flags.

    `debug_flag` is the flag that opens the debug channel; `prefs` are the
    profile preferences that channel needs (empty for browsers that need none);
    `stealth` is the sentence the panel shows about automation signals.
    """

    id: str
    label: str
    protocol: str
    port_offset: int
    dir_flag: str
    data_dir_default: str
    extra_args_default: str = ""
    executables: Dict[str, str] = field(default_factory=dict)
    notes: str = ""
    debug_flag: str = REMOTE_DEBUGGING_PORT
    prefs: Tuple[Tuple[str, object], ...] = ()
    stealth: str = ""

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
    BrowserProfile(
        id="firefox", label="Firefox (Mozilla)", protocol=PROTOCOL_RDP, port_offset=1,
        dir_flag="-profile", data_dir_default="",
        extra_args_default="-no-remote",
        executables={
            "windows": '"C:\\Program Files\\Mozilla Firefox\\firefox.exe"',
            "linux": "firefox",
            "macos": '"/Applications/Firefox.app/Contents/MacOS/firefox"',
        },
        notes=("DevTools RDP (--start-debugger-server): tabs, JS, click — attach and detach "
               "without touching the browser, and no automation flag. Starts with YOUR profile "
               "by default (leave the dir empty), which is the session you browse in — real "
               "history, cookies and extensions. -no-remote is what makes the socket open at "
               "all: without it the flag is handed to the already-running Firefox and no server "
               "starts. Neither flag is a remote-control switch. There is no input, screenshot "
               "or file API, and the Remote Agent (--remote-debugging-port) would set "
               "navigator.webdriver for the session."),
        debug_flag=START_DEBUGGER_SERVER,
        prefs=(
            ("devtools.chrome.enabled", True),
            ("devtools.debugger.remote-enabled", True),
            ("devtools.debugger.prompt-connection", False),
            ("devtools.debugger.force-local", True),
        ),
        stealth=("What the URL-bar robot icon really is: Firefox's own 'under remote control' "
                 "cue (#remote-control-icon, tooltip 'reason: DevTools'). It appears whenever a "
                 "DevTools server is running — it is NOT caused by -profile/-no-remote, and no "
                 "preference removes it while the socket is open. It is browser chrome: web pages "
                 "cannot see it, and the app measures what they CAN see — navigator.webdriver="
                 "false, no headless marker, a real profile. The 'Allow connection?' dialog is "
                 "devtools.debugger.prompt-connection: click Allow once, or let Prepare Profile "
                 "write that pref into the profile Firefox is actually running (it asks once per "
                 "connection, so the app opens one connection per pass). Never start Firefox with "
                 "--remote-debugging-port (Firefox bug 1719505 sets navigator.webdriver for the "
                 "whole session)."),
    ),
    BrowserProfile(
        id="edge", label="Edge (Chromium)", protocol=PROTOCOL_CDP, port_offset=2,
        dir_flag="--user-data-dir", data_dir_default="C:\\arena-images-edge",
        extra_args_default="",
        executables={
            "windows": '"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"',
            "linux": "microsoft-edge",
            "macos": '"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"',
        },
        notes="Chromium, so it speaks the same CDP as Chrome.",
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
    """The browser a fresh install uses (Chrome — the app's original one)."""
    return PROFILES[0]


def resolve_port(base_port, profile: BrowserProfile, override=None) -> int:
    """Endpoint port: the per-browser override, else the shared base + the offset.

    Two TCP servers cannot share one port, so the shared `cdp_port` is the BASE
    and each browser derives its own endpoint (Chrome +0, Firefox +1, …). The
    panel always shows the resolved number, so the setting stays predictable.
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
    """The flag that opens this browser's debug channel.

    Chrome/Edge take `--remote-debugging-port=<n>`; Firefox's DevTools server
    takes a space (`--start-debugger-server <n>`) and is a different channel from
    the flagged Remote Agent — which is the whole point of this row (D-4).
    """
    if profile.debug_flag == START_DEBUGGER_SERVER:
        return f"--{START_DEBUGGER_SERVER} {int(port)}"
    return f"--{profile.debug_flag}={int(port)}"


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
    return sorted(CAPABILITIES.get(profile.protocol, frozenset()))


def supports(browser_id: str, op: str, protocol: str = "") -> bool:
    """Can this browser do `op`? The one gate before a CDP-only operation runs."""
    profile = profile_of(browser_id)
    key = protocol or (profile.protocol if profile else "")
    return op in CAPABILITIES.get(key, frozenset())


def default_data_dir(browser_id: str) -> str:
    """Configured default profile dir of a browser ('' for an unknown id)."""
    profile = profile_of(browser_id)
    return profile.data_dir_default if profile else ""


def profile_for_protocol(protocol: str) -> Optional[BrowserProfile]:
    """The first registered browser that speaks this protocol (None when none does).

    Handles carry a channel rather than a browser id (a url cannot name a row), so
    this is how a handle with no id — `rdp://host:port/ctx-3` — still gets a label,
    a registry row and the flag that opens it.
    """
    want = (protocol or "").strip().lower()
    for profile in PROFILES:
        if profile.protocol == want:
            return profile
    return None


def browser_for_port(port, base_port=9222, overrides: Optional[Dict[str, Dict]] = None) -> str:
    """Which browser owns this endpoint — the ids are `base + offset` (round 9, D-1).

    One rule instead of an extra field on every handle: a pooled row's browser, an
    `rdp://` handle's owner and the Settings scan line all come from this lookup.
    """
    try:
        want = int(port)
    except Exception:
        return ""
    for profile in PROFILES:
        entry = (overrides or {}).get(profile.id) or {}
        if resolve_port(base_port, profile, entry.get("port")) == want:
            return profile.id
    return ""


def prefs_of(browser_id: str) -> Tuple[Tuple[str, object], ...]:
    """The profile preferences this browser's debug channel needs (() when none)."""
    profile = profile_of(browser_id)
    return profile.prefs if profile else ()


def endpoint_kind(browser_id: str) -> str:
    """`cdp` / `rdp` / `bidi` / `''` — the protocol this browser is expected to speak."""
    profile = profile_of(browser_id)
    return profile.protocol if profile else ""

"""Browser registry — more than one browser, one data-driven table (2026-09-21).

Owner request: Firefox next to Chrome, same host/port setting, per-browser data
dir + launch command, other browsers later. This module is the ONE place that
knows a browser's binaries, flags, default profile dir and protocol; adding a
browser later is one row here, not a new code path.

Protocol reality (measured 2026-09-21, stealth-fixed 2026-09-22):
* Chrome/Edge/Chromium speak CDP (`GET /json/list`, one socket per tab).
* Firefox speaks the DevTools Remote Debugging Protocol (RDP) over plain TCP
  (`--start-debugger-server`): no Marionette, no WebDriver session, so
  `navigator.webdriver` stays `false`. WebDriver BiDi was tried and removed —
  `--remote-debugging-port` taints the browser by design.
* An ESR 128/140 profile with `remote.active-protocols=2` still answers CDP.
`detect_protocol` in `endpoints.py` decides per endpoint; `capabilities` states
what each protocol can do, so a CDP-only operation can refuse by name.

RED at `bce5a01`: this module did not exist.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

PROTOCOL_CDP = "cdp"
PROTOCOL_RDP = "rdp"

# What each protocol can do today (the one gate a CDP-only op asks, D-3).
CAPABILITIES: Dict[str, frozenset] = {
    PROTOCOL_CDP: frozenset({"tabs", "evaluate", "navigate", "screenshot",
                             "set_files", "input", "dom"}),
    PROTOCOL_RDP: frozenset({"tabs", "evaluate", "navigate"}),
}


@dataclass(frozen=True)
class BrowserProfile:
    """One browser: identity, endpoint offset, profile dir, binaries, flags."""

    id: str
    label: str
    protocol: str
    port_offset: int
    dir_flag: str
    data_dir_default: str
    debug_arg: str = "--remote-debugging-port"
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
    BrowserProfile(
        id="firefox", label="Firefox (Mozilla)", protocol=PROTOCOL_RDP, port_offset=1,
        dir_flag="", data_dir_default="C:\\arena-images-firefox",
        debug_arg="--start-debugger-server",
        extra_args_default="",
        executables={
            "windows": '"C:\\Program Files\\Mozilla Firefox\\firefox.exe"',
            "linux": "firefox",
            "macos": '"/Applications/Firefox.app/Contents/MacOS/firefox"',
        },
        notes=("Stealth RDP (debugger server): tabs, JS, navigation, with "
               "navigator.webdriver=false. Launch Firefox yourself with "
               "--start-debugger-server=PORT on your real profile — no -profile, "
               "no -no-remote needed to attach. Close other Firefox windows "
               "first (or add -no-remote), or the flag joins the running "
               "instance and no server starts. Add --profile=\"...\" in extra "
               "args for an isolated profile; never --remote-debugging-port "
               "(that taints the session). "
               "First contact shows one \"Incoming Connection\" prompt in "
               "Firefox — click OK once. The app then switches the prompt off "
               "(devtools.debugger.prompt-connection=false) so later scans "
               "stay silent; flip it back in about:config to be asked again."),
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


def build_command(profile: BrowserProfile, os_name: str, target: dict) -> str:
    """One launch command: binary + debug-server flag + profile dir + args (+ URL).

    An empty `dir_flag` (manual-launch Firefox) skips the dir part entirely.
    """
    parts = [profile.binary(os_name), f"{profile.debug_arg}={int(target['port'])}"]
    if profile.dir_flag:
        parts.append(f'{profile.dir_flag}="{target["data_dir"]}"')
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


def endpoint_kind(browser_id: str) -> str:
    """`cdp` / `rdp` / `''` — the protocol this browser is expected to speak."""
    profile = profile_of(browser_id)
    return profile.protocol if profile else ""

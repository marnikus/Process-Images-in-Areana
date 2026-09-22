"""Stealth preflight — the constraints, written down and checked (I-62).

The anti-detection requirement is not a property of our client code; it is a
property of **how the user launched Firefox**. So the rules live here as data
and as two checks the app can actually run:

* `forbidden_flags(argv)` — the command line must not carry the flags that
  make `navigator.webdriver` true. Verified against Firefox source
  (`dom/base/Navigator.cpp`, `Navigator::Webdriver`): the property is true iff
  **Marionette** or the **Remote Agent** reports browser automation running.
  `--start-debugger-server` is the DevTools server — a third mechanism that
  the property never consults. That is exactly why this pipeline uses it.
* `required_prefs()` — the three prefs the DevTools server needs, so the
  operator can be told precisely what to set instead of guessing.

`launch_command(...)` only *renders* the command for the human to run: the
app never spawns the browser (a framework-launched browser is what the
constraint forbids). Nothing here has side effects.

Layer: browser leaf — pure data and predicates; no sockets, no Qt.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

__all__ = ["FORBIDDEN_FLAGS", "REQUIRED_PREFS", "forbidden_flags", "required_prefs",
           "launch_command", "stealth_warnings", "SIGNAL_LABELS"]

# Flags that flip navigator.webdriver (Marionette / Remote Agent), plus the
# headless switch the constraint forbids. `--start-debugger-server` is absent
# on purpose: it starts the DevTools server, which the property never reads.
FORBIDDEN_FLAGS = {
    "--marionette": "starts Marionette — navigator.webdriver becomes true",
    "--remote-debugging-port": "starts the Remote Agent (BiDi/CDP) — navigator.webdriver becomes true",
    "--headless": "headless is a strong automation signal and is out of scope",
    "--screenshot": "implies headless shot mode, not an interactive session",
}

REQUIRED_PREFS = {
    "devtools.debugger.remote-enabled": True,   # allow the DevTools server at all
    "devtools.chrome.enabled": True,            # allow the console actor to evaluate
    "devtools.debugger.prompt-connection": False,  # no modal on every attach/reattach
}

SIGNAL_LABELS = {
    "webdriver": "navigator.webdriver is true — a WebDriver engine is running",
    "hasCdc": "a cdc_ driver variable is present — a Chromium driver injected itself",
}


def _normalise(flag: str) -> str:
    """`-marionette`, `--marionette=1` → `--marionette` (Firefox accepts all forms)."""
    text = str(flag or "").strip().split("=", 1)[0]
    stripped = text.lstrip("-")
    return f"--{stripped.lower()}" if stripped else ""


def forbidden_flags(argv: Iterable[str]) -> List[str]:
    """Which automation-exposing flags this command line carries ([] = clean)."""
    seen = {_normalise(a) for a in argv or []}
    return sorted(flag for flag in FORBIDDEN_FLAGS if flag in seen)


def required_prefs() -> Dict[str, bool]:
    """The prefs the operator must set in the real profile (a copy, never the module dict)."""
    return dict(REQUIRED_PREFS)


def launch_command(binary: str, profile: str, port: int = 6000) -> List[str]:
    """The exact command the *user* runs — GUI, real profile, DevTools server only.

    Rendered for display: the app never executes it, because a browser started
    by the automation is the footprint the whole design avoids.
    """
    argv = [binary or "firefox"]
    if profile:
        argv += ["-P", profile]
    argv += ["--start-debugger-server", str(int(port))]
    return argv


def stealth_warnings(argv: Iterable[str], signals: Dict[str, bool] | None = None) -> List[str]:
    """Every reason this session is NOT stealthy, as operator-readable lines.

    Empty means clean — and empty is only ever returned because nothing was
    found, never because a check could not run (RULE 4).
    """
    lines = [f"⚠ {flag} — {FORBIDDEN_FLAGS[flag]}" for flag in forbidden_flags(argv)]
    for key, tripped in (signals or {}).items():
        if tripped and key in SIGNAL_LABELS:
            lines.append(f"⚠ {SIGNAL_LABELS[key]}")
    return lines

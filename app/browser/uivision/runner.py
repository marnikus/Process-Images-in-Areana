"""Launching a Ui.Vision macro in Firefox and waiting for its verdict.

The whole control flow of this feature:

1. delete the stale log, so the verdict we read cannot be the previous run's
2. `firefox <autorun-url>` — a normal browser tab, no debugger port, no driver
3. poll the log until it reports OK / error, or the deadline passes

Firefox is launched with **no automation flags whatsoever** — no
`--start-debugger-server`, no `--marionette`, no `-profile`, no `-no-remote`.
The user's normal browser and profile open a normal tab; everything after that
happens inside the signed extension. `LAUNCH_BANNED_FLAGS` states that as data
and `_check_flags` enforces it, so a future "just add one flag" cannot quietly
reintroduce a detectable browser.

A timeout is reported, never raised: a macro that is still running when the
deadline passes is a *result the operator must see*, not a crash.

Layer: browser leaf — subprocess + polling; no Qt, no services, no UI.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from .command_url import MacroRun, build_autorun_url
from .run_log import FAILED, OK, PENDING, RunVerdict, clear_log, read_verdict

__all__ = ["MacroOutcome", "LAUNCH_BANNED_FLAGS", "launch_argv", "run_macro",
           "poll_verdict", "DEFAULT_TIMEOUT_S", "POLL_INTERVAL_S"]

DEFAULT_TIMEOUT_S = 60.0
POLL_INTERVAL_S = 0.5

# Flags that would turn the user's browser into an automated one. The point of
# this feature is that none of them is ever passed (see docs I-65).
LAUNCH_BANNED_FLAGS = frozenset({
    "--start-debugger-server", "-start-debugger-server",
    "--marionette", "-marionette",
    "--remote-debugging-port", "-remote-debugging-port",
    "--headless", "-headless",
})


@dataclass(frozen=True)
class MacroOutcome:
    """How a macro run ended, and what the log said."""

    state: str = PENDING
    message: str = ""
    url: str = ""
    lines: Optional[List[str]] = None

    @property
    def ok(self) -> bool:
        return self.state == OK

    @property
    def timed_out(self) -> bool:
        """Never reached a verdict before the deadline (still PENDING)."""
        return self.state == PENDING


def _check_flags(argv: Sequence[str]) -> None:
    """Refuse to launch a browser carrying an automation flag."""
    for arg in argv:
        head = str(arg).split("=", 1)[0].lower()
        if head in LAUNCH_BANNED_FLAGS:
            raise ValueError(f"{head} would expose automation — Ui.Vision needs a normal browser")


def launch_argv(binary: str, url: str, new_tab: bool = True) -> List[str]:
    """The exact command: the browser, optionally `-new-tab`, and the URL.

    Nothing else is ever added — that absence is the feature.
    """
    argv = [str(binary or "firefox")]
    if new_tab:
        argv.append("-new-tab")
    argv.append(url)
    _check_flags(argv)
    return argv


async def poll_verdict(log_path: Any, timeout: float = DEFAULT_TIMEOUT_S,
                       interval: float = POLL_INTERVAL_S) -> RunVerdict:
    """Watch the log until it reaches a verdict or the deadline passes."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max(timeout, 0)
    verdict = read_verdict(log_path)
    while not verdict.is_done and loop.time() < deadline:
        await asyncio.sleep(interval)
        verdict = read_verdict(log_path)
    return verdict


def _spawn(argv: List[str]) -> None:
    """Start the browser and do not wait — the macro runs in the tab."""
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def run_macro(run: MacroRun, binary: str = "firefox",
                    timeout: float = DEFAULT_TIMEOUT_S) -> MacroOutcome:
    """Run one macro end to end: clear log → open tab → poll for the verdict."""
    gaps = run.missing()
    if gaps:
        return MacroOutcome(state=FAILED, message="; ".join(gaps))
    if run.log_path and not clear_log(run.log_path):
        return MacroOutcome(state=FAILED, message=f"cannot clear log {run.log_path}")
    url = build_autorun_url(run)
    try:
        await asyncio.get_event_loop().run_in_executor(
            None, _spawn, launch_argv(binary, url))
    except (OSError, ValueError) as exc:
        return MacroOutcome(state=FAILED, message=str(exc), url=url)
    return _as_outcome(await poll_verdict(run.log_path, timeout), url, timeout)


def _as_outcome(verdict: RunVerdict, url: str, timeout: float) -> MacroOutcome:
    """A log verdict as a run outcome; a timeout says so in words."""
    message = verdict.message or (f"no verdict in {timeout:g}s — is the macro "
                                  f"installed and XModules running?")
    return MacroOutcome(state=verdict.state, message=message, url=url,
                        lines=verdict.lines or [])


def find_firefox(candidates: Optional[Sequence[str]] = None) -> str:
    """The Firefox binary to launch: the first that exists ('' when none does)."""
    for name in candidates or ("firefox", "firefox.exe"):
        found = shutil.which(str(name))
        if found:
            return found
    return ""

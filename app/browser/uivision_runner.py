"""Ui.Vision macro runner — provision, gate, spawn Firefox, wait for savelog.

App-driven end of the 2026-09-23 "Can't find macro" fix (`uivision_autorun`
owns the pure pieces; this module owns the process + wait). The caller
supplies paths + macro commands — everything else happens here:

1. provision the macro with selectWindow|title=*{pattern}* first,
2. refuse unless the on-disk macro pre-flights ok (missing|invalid),
3. spawn Firefox with the %-encoded autorun URL (tab= cannot be sent),
4. wait for the savelog's first status line until the deadline.

Spawn + sleep + report are injectable (`RunHooks`) so tests run the real wait
logic against fakes (RULE 8), the way pipelines run against fake CDP clients.
No Qt. Result: {"ok", "outcome", "detail", "savelog"}; outcome is success |
macro-error | timeout | refused (RULE 4: every ending distinct).
"""

import datetime
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.browser.uivision_autorun import (
    autorun_query,
    launch_plan,
    macro_document,
    provision_macro,
)

#: Success marker on the savelog's first line (Ui.Vision writes it; the
#: documented PowerShell poller checks `-contains "Status=OK"`).
_STATUS_OK = "Status=OK"


@dataclass(frozen=True)
class UivisionRun:
    """One macro run: where things live, what to run, how long to wait."""

    home: str
    page_path: str
    macro: str
    pattern: str
    commands: list
    firefox_exe: str
    savelog: str = ""
    timeout_sec: float = 90.0
    poll_sec: float = 1.0


def _spawn_firefox(argv: list):
    """Default spawn seam: start the real Firefox with the autorun URL."""
    return subprocess.Popen(argv)


def _null_report(message: str, level: str = "info") -> None:
    """Default report seam: silence (the app passes its own logger)."""


@dataclass(frozen=True)
class RunHooks:
    """Injectable process boundary: spawn, sleep, report (all faked in tests)."""

    spawn: Callable = _spawn_firefox
    sleep: Callable = time.sleep
    report: Callable = _null_report


def default_savelog_path(macro: str) -> str:
    """Fallback savelog when the caller passes none: ./uivision-logs/<macro>-<stamp>.txt."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w-]+", "_", (macro or "macro").strip()).strip("_") or "macro"
    return os.path.join(os.getcwd(), "uivision-logs", f"{safe}-{stamp}.txt")


def _first_status_line(savelog: str):
    """First non-blank savelog line, or None while the file is missing/empty."""
    try:
        with open(savelog, encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                if raw.strip():
                    return raw.strip()
    except OSError:
        return None
    return None


def _finish_from_status(line: str, savelog: str, hooks: RunHooks) -> dict:
    """Map the savelog's first status line to the run result."""
    if _STATUS_OK in line:
        hooks.report(f"result: success — {line}")
        return {"ok": True, "outcome": "success", "detail": line, "savelog": savelog}
    hooks.report(f"result: macro error — {line}", "error")
    return {"ok": False, "outcome": "macro-error", "detail": line, "savelog": savelog}


def _await_savelog(run: UivisionRun, savelog: str, hooks: RunHooks) -> dict:
    """Poll the savelog until its status line appears or the deadline passes."""
    waited = 0.0
    while waited < run.timeout_sec:
        line = _first_status_line(savelog)
        if line is not None:
            return _finish_from_status(line, savelog, hooks)
        hooks.sleep(run.poll_sec)
        waited += run.poll_sec
    detail = f"no status line in {savelog} within {run.timeout_sec:g}s — check the extension ran the macro"
    hooks.report(f"result: timeout — {detail}", "error")
    return {"ok": False, "outcome": "timeout", "detail": detail, "savelog": savelog}


def _refused(detail: str, hooks: RunHooks, savelog: str) -> dict:
    """The gate said no: report once (RULE 2) and never spawn (the whole point)."""
    hooks.report(detail, "error")
    return {"ok": False, "outcome": "refused", "detail": detail, "savelog": savelog}


def run_macro(run: UivisionRun, hooks: RunHooks = RunHooks()) -> dict:
    """Provision, gate, spawn Firefox, wait for the savelog status (all steps here)."""
    savelog = run.savelog.strip() or default_savelog_path(run.macro)
    try:
        macro_path = provision_macro(run.home, run.macro,
                                     macro_document(run.macro, run.pattern, list(run.commands)))
    except OSError as exc:
        return _refused(f"cannot write macro {run.macro}: {exc}", hooks, savelog)
    hooks.report(f"provision: macro written: {macro_path}")
    plan = launch_plan(run.home, run.page_path, autorun_query(run.macro, savelog))
    if not plan["ok"]:
        return _refused(plan["error"], hooks, savelog)
    for key in plan["dropped"]:
        hooks.report(f"dropped ignored autorun param: {key}", "warn")
    try:
        proc = hooks.spawn([run.firefox_exe, plan["url"]])
    except OSError as exc:
        return _refused(f"cannot start {run.firefox_exe}: {exc}", hooks, savelog)
    hooks.report(f"launch: firefox started (pid {getattr(proc, 'pid', '?')}) — waiting for savelog")
    return _await_savelog(run, savelog, hooks)

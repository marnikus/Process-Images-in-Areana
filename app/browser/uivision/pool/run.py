"""One pool run: per-run macro → scoped foreground → launch → savelog verdict (I-64).

The launch + poll half is the framework's `Sequence`: the same argv checks,
`-profile`/`-P` targeting, Stop inside the poll, and the frozen verdict kinds
(ok / error / timeout / stopped / blocked). Only the foreground differs. A
pool run raises the ONE OS window mapped to its tab's session window and never
falls back to raising every Firefox window (owner rule: foreground only the
target profile's window). An unmapped or ambiguous window is named in the log
and left to the macro's own `bringBrowserToForeground`.

A pool run needs storage=xfile: its macro changes per run (anchor, offset),
and the browser storage can only play a macro imported once. No Qt, no bridge.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from .. import autorun, desktop, launch, paths, plan
from ..runner import Recorder, RunSeams, macro_target
from ..sequence import RunResult, Sequence, mapped_note
from ..macro import to_json
from .macro import PoolStep, build_pool_macro
from .scan import FoxTab

XFILE = "xfile"


@dataclass(frozen=True)
class PoolRunSpec:
    """The settings `Sequence` reads (duck-types `runner.RunSpec`) for one pool run."""

    binary: str
    macro: str            # the pool macro name (`{base}_pool`)
    storage: str
    home: str
    config_dir: str
    pause_ms: int
    target: str
    timeout_sec: int
    pattern: str = ""
    url_pattern: str = ""
    inter_run_delay_sec: int = 0


@dataclass(frozen=True)
class PoolJob:
    """One planned pool run: settings, the tab, its window row and the baked step."""

    spec: PoolRunSpec
    tab: FoxTab
    window_row: dict
    step: PoolStep


class PoolSequence(Sequence):
    """The framework sequence with a strictly scoped foreground."""

    def _foreground(self, run) -> None:
        rows = list(run.target.windows)
        mapped = desktop.foreground_tab_window(run.target.url, rows) if rows else None
        if mapped is None:
            self.recorder("foreground", "the tab's window maps to no OS window — nothing raised "
                                        "(never raise-all); the macro's "
                                        "bringBrowserToForeground decides", "warn")
            return
        note, level = mapped_note(*mapped, run.target.title or run.target.url)
        self.recorder("foreground", note, level)


def run_stamp() -> str:
    """A savelog stamp no other run shares (two quick runs in one second must not collide)."""
    return f"pool-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def planned_run(job: PoolJob, stamp: str) -> plan.PlannedRun:
    """The single `PlannedRun` of a pool job — its profile, its window, its own savelog."""
    tab = job.tab
    target = plan.Target(profile_name=tab.profile_name, profile_dir=tab.profile_dir,
                         url=tab.url, title=tab.title,
                         windows=(job.window_row,) if job.window_row else ())
    return plan.PlannedRun(
        target=target, index=1, total=1, label=f"{tab.profile_label} · {tab.id}",
        selector=f"title={job.step.anchor}",
        profile_args=launch.profile_args(tab.profile_name, tab.profile_dir),
        log_path=str(paths.log_file(job.spec.config_dir, stamp)))


def provision(job: PoolJob, report) -> object:
    """Write this run's macro into the XModule home + the autorun page; returns the page."""
    paths.logs_dir(job.spec.config_dir).mkdir(parents=True, exist_ok=True)
    target = macro_target(job.spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_json(build_pool_macro(job.spec.macro, job.step)), encoding="utf-8")
    offset = f" + tab={job.step.offset}" if job.step.offset else ""
    report("provision", f"pool macro written: {target} (title={job.step.anchor}{offset})")
    return autorun.write_page(paths.autorun_file(job.spec.config_dir))


def _blocked(message: str, recorder: Recorder) -> RunResult:
    recorder("provision", message, "error")
    return RunResult(kind="blocked", message=message, steps=tuple(recorder.steps))


async def run_pool_job(job: PoolJob, report, seams: RunSeams = None) -> RunResult:
    """Provision → scoped foreground → launch → poll; every step reports through `report`."""
    seams = seams or RunSeams()
    recorder = Recorder(report)
    if job.spec.storage != XFILE:
        return _blocked("Firefox pool jobs need storage=xfile (hard-drive mode) — the macro "
                        "is rewritten for every run; set it in the Firefox window", recorder)
    try:
        page = provision(job, recorder)
    except (ValueError, OSError) as exc:
        return _blocked(f"cannot prepare the run: {exc}", recorder)
    sequence = PoolSequence(job.spec, seams, recorder)
    sequence.page = str(page)
    return await sequence.execute([planned_run(job, run_stamp())])

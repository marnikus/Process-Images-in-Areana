"""The Firefox execution lane — Ui.Vision phase macros for the image job (2026-09-25).

Design D5/D6 (pool integration) + D-1 (image job): the dispatcher claims a
Firefox pool page exactly like a Chrome one and `services/firefox_job` drives
the job as short phase macros; THIS module runs one macro on one pool entry:
spec from the SAME validated config the window saves, locator FROM the pool
entry (`url_pattern` = the tab's own URL, the tab's own title as the hard
`selectWindow` fallback — never a foreground-constructed title), provision →
raise ONLY the target profile's window → launch (remoting forwards into the
RUNNING instance) → poll the savelog. One machine-wide `asyncio.Lock` = one
macro at a time (native input needs the foreground, §4.3); the window's own
`inter_run_delay_sec` is the owner's gap BETWEEN JOBS (owner Q4, 2026-09-25) —
`job_gap` / `note_job_end` — never between the phases of one job.

The identify macro (`run_identify`) shares the SAME lock and critical section
(`_run_locked`): account detection + the visual tab id overlay never race a job.

Layer: services → browser only (`uivision.config` is shared with the panel —
RULE 10).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from pathlib import Path

from app.browser.uivision import config as uv_config
from app.browser.uivision import identify as uv_identify
from app.browser.uivision import job_macros as uv_job
from app.browser.uivision import plan as uv_plan
from app.browser.uivision import tabs as uv_tabs
from app.browser.uivision.runner import RunSeams
from app.browser.uivision.sequence import Sequence, StepRecorder

log = logging.getLogger("arena")

_MACRO_LOCK = asyncio.Lock()   # one Ui.Vision macro at a time per machine (§4.3)
_LAST_AT = 0.0                 # monotonic stamp of the previous job's end
_GAP_DEFAULT = 3               # owner's default delay, seconds
_GAP_CEILING = 30


def _gap_seconds(cfg: dict) -> int:
    """The user-defined inter-job delay from the window's config, clamped."""
    try:
        return max(0, min(_GAP_CEILING, int(cfg.get("inter_run_delay_sec", _GAP_DEFAULT))))
    except Exception:
        return _GAP_DEFAULT


async def _wait_gap(cfg: dict) -> None:
    """Sleep out the remaining delay since the previous job (0 = straight in)."""
    global _LAST_AT
    left = _LAST_AT + _gap_seconds(cfg) - time.monotonic() if _LAST_AT else 0
    if left > 0:
        await asyncio.sleep(left)


def _job_config(bridge, page) -> dict:
    """Validated config retargeted at ONE pool entry: no title search, URL = the tab's."""
    cfg = dict(uv_config.load_config(bridge))
    cfg["pattern"] = ""
    cfg["url_pattern"] = page.url or cfg.get("url_pattern", "")
    return cfg


def _target_windows(page) -> tuple:
    """This profile's session windows — the foreground map (raise ONLY this instance)."""
    directory = getattr(page, "profile_dir", "") or ""
    sessions = uv_tabs.profile_sessions([directory] if directory else None)
    for session in sessions:
        if str(session.get("dir") or "") == directory:
            return tuple(session.get("windows") or ())
    return ()


def _planned_run(spec, page):
    """One PlannedRun for this entry: selector from the entry's own title/URL."""
    target = uv_plan.Target(profile_name=getattr(page, "profile", ""),
                            profile_dir=getattr(page, "profile_dir", ""),
                            url=page.url, title=page.title, windows=_target_windows(page))
    return uv_plan.runs([target], uv_plan.Patterns(spec.pattern, spec.url_pattern),
                        spec.config_dir, time.strftime("%Y%m%d-%H%M%S"))[0]


def _fresh(run):
    """Drop a stale savelog so a run never inherits an earlier verdict."""
    try:
        Path(run.log_path).unlink(missing_ok=True)
    except OSError:
        pass
    return run


async def job_gap(bridge) -> None:
    """The owner's inter-JOB delay (Q4: between jobs only, never between phases)."""
    await _wait_gap(uv_config.load_config(bridge))


def note_job_end() -> None:
    """Stamp the end of a job — the next job's gap counts from here."""
    global _LAST_AT
    _LAST_AT = time.monotonic()


async def _run_locked(spec, run, provision) -> tuple:
    """Lock → fresh savelog → provision → ONE run → (kind, message, savelog lines).

    No stop seam on purpose: a started macro always runs to its own verdict,
    so the lock is never released while Ui.Vision still drives the tab (an OS
    file dialog is never abandoned half-way); cancel is honoured between runs.
    """
    async with _MACRO_LOCK:
        _fresh(run)
        seq = Sequence(spec, RunSeams(), StepRecorder(_quiet_report))
        seq.page = provision(spec)
        result = await seq.execute([run])
    return result.kind, result.message, tuple(result.lines)


def _phase_spec(bridge, page, phase):
    """The pool entry's spec retargeted at one job phase macro (cmd_var1/2 per phase)."""
    spec = uv_config.build_spec(bridge, _job_config(bridge, page))
    return replace(spec, macro=phase.name, target=phase.xclick, pause_ms=phase.wait_ms,
                   timeout_sec=phase.timeout_sec)


async def run_phase(bridge, page, phase, token: str) -> tuple:
    """(kind, message, savelog lines) of one image-job phase macro on this pool entry."""
    spec = _phase_spec(bridge, page, phase)
    if spec.storage != "xfile":
        return "blocked", "the image job needs hard-drive macro storage (xfile)", ()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run = replace(_planned_run(spec, page),
                  log_path=uv_job.log_path(spec.config_dir, token, phase.phase, stamp))
    return await _run_locked(spec, run, lambda s: uv_job.provision(s, phase))


def _quiet_report(step: str, message: str, level: str = "info") -> None:
    """Identify steps go to the debug log only — the watcher words the user-facing line."""
    log.debug("identify %s: %s", step, message)


def _identify_spec(bridge, page, cmd_payload: str):
    """The job's spec retargeted at the identify macro: payload on cmd_var2, wait on cmd_var1."""
    spec = uv_config.build_spec(bridge, _job_config(bridge, page))
    return replace(spec, macro=uv_identify.MACRO_NAME, target=cmd_payload,
                   pause_ms=uv_identify.WAIT_MS)


async def run_identify(bridge, page, cmd_payload: str) -> tuple:
    """(kind, message, savelog lines) of one identify macro on this pool entry.

    Hard-drive storage only: the browser store cannot receive a written macro,
    so that configuration answers `blocked` before anything launches (RULE 4).
    """
    spec = _identify_spec(bridge, page, cmd_payload)
    if spec.storage != "xfile":
        return "blocked", "identify needs hard-drive macro storage (xfile)", ()
    await _wait_gap(uv_config.load_config(bridge))
    run = replace(_planned_run(spec, page),
                  log_path=uv_identify.log_path(spec.config_dir, time.strftime("%Y%m%d-%H%M%S")))
    result = await _run_locked(spec, run, uv_identify.provision)
    note_job_end()
    return result

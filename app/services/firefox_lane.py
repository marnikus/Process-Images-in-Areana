"""The Firefox execution lane — one Ui.Vision macro = one dispatched job (2026-09-25).

Design D5/D6: the dispatcher claims a Firefox pool page exactly like a Chrome
one; this lane runs the job: spec from the SAME validated config the window
saves, locator FROM the pool entry (`url_pattern` = the tab's own URL → the
macro's guarded `selectWindow url=*…*`, then the tab's own title as the hard
fallback — never a foreground-constructed title), provision → raise ONLY the
target profile's window → launch (remoting forwards into the RUNNING instance)
→ poll the savelog. Machine-wide `asyncio.Lock` + the window's own
`inter_run_delay_sec` give the owner's "one macro at a time + user-defined
3 s delay" contract (§4.3). Cancel is honoured before launch and inside the
poll (RULE 7); every step logs with the 🦊 marker (RULE 2).

The identify macro (2026-09-25, `run_identify`) shares the SAME lock and gap:
account detection + the visual tab id overlay never race a job macro.

Layer: services → browser only (`uivision.config` was extracted so the panel
and this lane share one validation/spec builder — RULE 10).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from pathlib import Path

from app.browser.uivision import config as uv_config
from app.browser.uivision import identify as uv_identify
from app.browser.uivision import plan as uv_plan
from app.browser.uivision import runner as uv_runner
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


def _job_run(spec, page):
    """The job's planned run with a fresh savelog file."""
    return _fresh(_planned_run(spec, page))


def _reporter(bridge):
    """One report callback: every step lands in the app log (RULE 2)."""
    def report(step: str, message: str, level: str = "info") -> None:
        bridge._log(f"🦊 {step}: {message}", level)
    return report


async def _execute(spec, run, bridge, report) -> tuple:
    """Provision + run the single planned run; seams carry cancel (RULE 7)."""
    seq = Sequence(spec, RunSeams(stop=lambda: bool(getattr(bridge, "_cancel_requested", False))),
                   StepRecorder(report))
    seq.page = str(uv_runner.provision(spec, report))
    result = await seq.execute([run])
    return result.kind, result.message


async def run_firefox_macro(bridge, page) -> tuple:
    """(kind, message) for this pool entry's job — kinds follow the savelog contract."""
    global _LAST_AT
    if getattr(bridge, "_cancel_requested", False):
        return "stopped", "cancelled before the macro launched"
    cfg = _job_config(bridge, page)
    spec = uv_config.build_spec(bridge, cfg)
    run = _job_run(spec, page)
    report = _reporter(bridge)
    async with _MACRO_LOCK:
        await _wait_gap(cfg)
        report("lane", f"macro job on {page.tab_id} — selector {run.selector or 'any tab'}, "
                       f"savelog {Path(run.log_path).name}")
        kind, message = await _execute(spec, run, bridge, report)
        _LAST_AT = time.monotonic()
    return kind, message


def _quiet_report(step: str, message: str, level: str = "info") -> None:
    """Identify steps go to the debug log only — the watcher words the user-facing line."""
    log.debug("identify %s: %s", step, message)


def _identify_spec(bridge, page, cmd_payload: str):
    """The job's spec retargeted at the identify macro: payload on cmd_var2, wait on cmd_var1."""
    spec = uv_config.build_spec(bridge, _job_config(bridge, page))
    return replace(spec, macro=uv_identify.MACRO_NAME, target=cmd_payload,
                   pause_ms=uv_identify.WAIT_MS)


# ideal-size: 21 lines reason=lock + gap + provision + run + read-back must stay in one critical section; splitting would leak the macro lock across helpers
async def run_identify(bridge, page, cmd_payload: str) -> tuple:
    """(kind, message, savelog lines) of one identify macro on this pool entry.

    Hard-drive storage only: the browser store cannot receive a written macro,
    so that configuration answers `blocked` before anything launches (RULE 4).
    """
    global _LAST_AT
    spec = _identify_spec(bridge, page, cmd_payload)
    if spec.storage != "xfile":
        return "blocked", "identify needs hard-drive macro storage (xfile)", ()
    run = replace(_planned_run(spec, page),
                  log_path=uv_identify.log_path(spec.config_dir, time.strftime("%Y%m%d-%H%M%S")))
    async with _MACRO_LOCK:
        _fresh(run)
        await _wait_gap(uv_config.load_config(bridge))
        seq = Sequence(spec, RunSeams(), StepRecorder(_quiet_report))
        seq.page = uv_identify.provision(spec)
        result = await seq.execute([run])
        _LAST_AT = time.monotonic()
    return result.kind, result.message, tuple(result.lines)

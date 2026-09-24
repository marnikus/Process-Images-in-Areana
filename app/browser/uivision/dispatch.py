# ideal-size: 321 lines reason=one run's scan, launch and per-tab verdict share one log contract; splitting the wording from the step that emits it would hide which line the window shows
"""Run the Ui.Vision macro on every matching tab in every open Firefox profile.

The window calls this, not `runner.run_test`. That helper launches
`[binary, url]`, which Firefox hands to the last-used profile only. Each
launch here carries `-P <name>` (or `--profile <path>`) so the running
instance of *that* profile receives the autorun URL. Tabs run one after
another: XClick is native input, and two at once would fight for the pointer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import autorun, desktop, launch, logread, paths, runner
from .profiles import argv_for, matching_jobs, scan_open, tab_matches


@dataclass
class ProfileSeams:
    """Test seams. `profiles` is `() -> (opened, closed)` — None scans the disk."""

    stop: object = None
    sleep: object = None
    popen: object = None
    profiles: object = None
    addon: object = None
    probe: object = None


# The window imports this name (same shape as the single-profile seams).
RunSeams = ProfileSeams


@dataclass
class _Call:
    spec: object
    job: dict
    index: int
    total: int
    page: object
    binary: str
    recorder: object
    seams: ProfileSeams
    stamp: str = ""


async def run_profiles(spec, report, seams=None):
    """Scan every open profile, then run the macro on each matching tab."""
    return await _run(spec, report, seams or ProfileSeams())


async def _run(spec, report, seams):
    recorder = runner._Recorder(report)
    opened, closed = _scan(spec, recorder, seams)
    if _stopped(seams):
        return _done("stopped", "stopped before the run began", recorder)
    if runner.tab_target(spec.pattern) is None:
        return runner._blocked_no_pattern(recorder)
    jobs = matching_jobs(opened, spec.pattern)
    if not any(not job.get("skipped") for job in jobs):
        return _done("blocked", _empty_message(opened, spec.pattern), recorder)
    return await _run_jobs(spec, jobs, recorder, seams)


def _scan(spec, recorder, seams):
    opened, closed = seams.profiles() if seams.profiles else scan_open()
    _log_scan(opened, closed, recorder)
    for profile in opened:
        _log_profile(profile, spec.pattern, recorder)
    runner._detect_plugin(recorder, seams)
    return opened, closed


def _log_scan(opened, closed, recorder):
    labels = ", ".join(p.get("label", "?") for p in opened[:8]) or "none"
    recorder("detect", f"firefox profiles open: {len(opened)} ({labels}); {_closed_note(closed)}")


def _closed_note(closed) -> str:
    if not closed:
        return "0 closed skipped"
    names = ", ".join(_path_name(path) for path in list(closed)[:6])
    extra = f" +{len(closed) - 6}" if len(closed) > 6 else ""
    return f"{len(closed)} closed skipped ({names}{extra})"


def _path_name(path) -> str:
    return Path(path).name


def _log_profile(profile, pattern, recorder):
    rows = profile.get("rows") or []
    hits = [row for row in rows if tab_matches(row, pattern)]
    source = profile.get("source") or "no session file"
    lock = "" if profile.get("lock") != "unknown" else " (lock check failed, session is fresh)"
    recorder("detect",
             f"profile {profile.get('label')}: {len(rows)} tab(s), "
             f"{len(hits)} match “{pattern}” ({source}){lock}")
    _log_hits(hits, recorder)


def _log_hits(hits, recorder):
    for index, row in enumerate(hits[:20], 1):
        url = str(row.get("url") or "")[:110]
        title = str(row.get("title") or "")[:40]
        recorder("detect", f"match {index}: {url} — {title}")
    if len(hits) > 20:
        recorder("detect", f"+{len(hits) - 20} more matching tab(s)")


def _empty_message(opened, pattern) -> str:
    if not opened:
        return "no open Firefox profile — nothing launched (a closed profile is not started)"
    return f"no tab matches “{pattern}” in {len(opened)} open profile(s) — nothing launched"


def _stopped(seams) -> bool:
    return bool(seams.stop and seams.stop())


def _done(kind, message, recorder):
    return runner.RunResult(kind=kind, message=message, steps=tuple(recorder.steps))


async def _run_jobs(spec, jobs, recorder, seams):
    binary = _binary(spec, recorder)
    if not binary:
        return _done("blocked", "Firefox was not found — nothing was launched", recorder)
    try:
        page = runner._provision(spec, recorder)[0]
    except (ValueError, OSError) as exc:
        recorder("provision", f"cannot prepare the run: {exc}", "error")
        return _done("blocked", str(exc), recorder)
    outcomes = []
    total = len(jobs)
    for index, job in enumerate(jobs, 1):
        if _stopped(seams):
            return _stopped_after(outcomes, recorder)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-t{index}"
        outcome = await _one_tab(
            _Call(spec, job, index, total, page, binary, recorder, seams, stamp))
        if outcome["kind"] == "stopped":
            return _stopped_after(outcomes, recorder)
        outcomes.append(outcome)
    return _summary(outcomes, jobs, recorder)


def _binary(spec, recorder) -> str:
    binary = launch.resolve_binary(spec.binary)
    if launch.binary_exists(binary):
        return binary
    recorder("launch", launch.diagnose_binary(binary), "error")
    return ""


async def _one_tab(call: _Call):
    if call.job.get("skipped"):
        return _skip(call)
    if not _still_open(call):
        return _closed_now(call)
    _raise(call)
    if _stopped(call.seams):
        return {"kind": "stopped", "message": "stopped before this tab's launch", "lines": ()}
    try:
        process = _launch_tab(call)
    except (OSError, ValueError) as exc:
        call.recorder("launch", f"profile {call.job.get('label')}: Firefox would not start: {exc}", "error")
        return {"kind": "blocked", "message": str(exc), "lines": ()}
    if process is None:
        call.recorder("launch", f"profile {call.job.get('label')}: Firefox did not start", "error")
        return {"kind": "blocked", "message": "Firefox did not start", "lines": ()}
    return await _poll(call)


def _still_open(call: _Call) -> bool:
    """Re-check the lock unless the test injected the profile list."""
    if call.seams.profiles:
        return True
    from .profiles import _keep
    return _keep(call.job.get("path"))


def _skip(call: _Call):
    job = call.job
    call.recorder("result",
                  f"profile {job.get('label')} tab {call.index}/{call.total}: skipped "
                  f"{str(job.get('url') or '')[:80]} — same title as an earlier tab in "
                  f"this profile (selectWindow would hit that tab again)",
                  "warn")
    return {"kind": "skipped", "message": "same title as an earlier tab", "lines": ()}


def _closed_now(call: _Call):
    job = call.job
    call.recorder("result",
                  f"profile {job.get('label')} closed before this tab launched — skipped, "
                  f"not started",
                  "warn")
    return {"kind": "skipped", "message": "profile closed before launch", "lines": ()}


def _raise(call: _Call):
    """Best-effort: a window we cannot raise must not stop the launch."""
    try:
        _raise_window(call)
    except Exception as exc:
        call.recorder("foreground",
                      f"profile {call.job.get('label')}: could not raise a window ({exc}) — launching anyway",
                      "warn")


def _raise_window(call: _Call):
    job = call.job
    mapped = desktop.foreground_tab_window(call.spec.pattern, job.get("windows") or [])
    if mapped:
        call.recorder("foreground", f"profile {job.get('label')}: window on top (holds a matching tab)")
        return
    matches, raised = desktop.foreground(call.spec.pattern)
    if matches:
        call.recorder("foreground", f"profile {job.get('label')}: {raised}/{len(matches)} window(s) on top")
        return
    call.recorder("foreground",
                  f"profile {job.get('label')}: no OS window matched — launching into the profile anyway",
                  "warn")


def _launch_tab(call: _Call):
    log_path = paths.log_file(call.spec.config_dir, call.stamp)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    url = autorun.launch_url(_launch_spec(call, log_path))
    argv = argv_for(call.binary, url, call.job)
    call.recorder("launch", _launch_line(call, argv))
    return launch.launch_resilient(argv, popen=call.seams.popen)


def _launch_spec(call: _Call, log_path):
    spec = call.spec
    return autorun.LaunchSpec(page_path=str(call.page), macro=spec.macro, storage=spec.storage,
                              log_path=str(log_path), pause_ms=spec.pause_ms, target=spec.target,
                              tab=call.job.get("target") or "")


def _launch_line(call: _Call, argv) -> str:
    job = call.job
    flag = " ".join(str(part) for part in argv[1:-1])
    note = " (tab has no title — selectWindow uses the pattern)" if job.get("untitled") else ""
    return (f"profile {job.get('label')} tab {call.index}/{call.total}: {flag} — "
            f"{str(job.get('url') or '')[:80]} — target {job.get('target')}{note}")


async def _poll(call: _Call):
    log_path = paths.log_file(call.spec.config_dir, call.stamp)
    verdict = await logread.poll_log(log_path, time.time() + float(call.spec.timeout_sec),
                                     sleep=call.seams.sleep, stop=call.seams.stop)
    _log_verdict(call, verdict)
    return {"kind": verdict.kind, "message": verdict.message, "lines": verdict.lines}


def _log_verdict(call: _Call, verdict):
    job = call.job
    level = "info" if verdict.kind == "stopped" else runner._result_level(verdict.kind)
    call.recorder("result",
                  f"profile {job.get('label')} tab {call.index}/{call.total}: "
                  f"{verdict.kind}: {verdict.message} — {str(job.get('url') or '')[:80]}",
                  level)


def _summary(outcomes, jobs, recorder):
    kind = _overall(outcomes)
    text = _summary_text(outcomes, jobs)
    level = "info" if kind == "stopped" else runner._result_level(kind)
    recorder("result", text, level)
    return runner.RunResult(kind=kind, message=text, steps=tuple(recorder.steps),
                            lines=_lines(outcomes))


_KIND_RANK = {"ok": 0, "timeout": 1, "corrupt": 2, "error": 2, "blocked": 3, "stopped": 4}


def _overall(outcomes) -> str:
    launched = [item["kind"] for item in outcomes if item["kind"] != "skipped"]
    if not launched:
        return "blocked"
    worst = max(launched, key=lambda kind: _KIND_RANK.get(kind, 2))
    return "error" if worst == "corrupt" else worst


def _labels(jobs) -> list:
    labels = []
    for job in jobs:
        label = job.get("label") or "?"
        if label not in labels:
            labels.append(label)
    return labels


def _summary_text(outcomes, jobs) -> str:
    launched = [item for item in outcomes if item["kind"] != "skipped"]
    skipped = len(outcomes) - len(launched)
    ok = sum(1 for item in launched if item["kind"] == "ok")
    extra = f"; {skipped} skipped (same title or profile closed)" if skipped else ""
    return (f"{ok}/{len(launched)} tab(s) ok, {len(jobs)} matching, across "
            f"{len(_labels(jobs))} profile(s): {', '.join(_labels(jobs))}{extra}")


def _lines(outcomes) -> tuple:
    out = []
    for item in outcomes:
        out.extend(item.get("lines") or ())
    return tuple(out)


def _stopped_after(outcomes, recorder):
    done = len(outcomes)
    text = f"stopped after {done} tab(s)"
    recorder("result", text, "warn")
    return runner.RunResult(kind="stopped", message=text, steps=tuple(recorder.steps),
                            lines=_lines(outcomes))

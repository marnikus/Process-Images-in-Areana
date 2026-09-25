"""The planned runs, executed in order — resolve → deliver → poll each.

One run per profile (2026-09-24 lifecycle redesign): each attempt resolves its
selector fresh (the title literal, or a `tab=N` from a re-read session store —
a tab gone since detect SKIPS without aborting the other profiles), raises the
window, delivers the autorun URL WITHOUT remoting (address-bar keys, CLI cold
start, or the manual fallback that still polls the savelog) and polls for the
verdict. A `selectWindow` miss ("failed to find the tab with locator" — the
macro died on its FIRST command, before any click) retries ONCE with a fresh
resolve; the extension is flaky there and the retry cannot double-click. After
the last verdict the protected-tab check (`guard`) warns for any pre-existing
tab missing from the store. Stop is honoured before every run, inside every
poll and before the retry (RULE 7); kinds stay frozen + `skipped` (RULE 4).
No Qt, no bridge: report/stop/sleep/popen/deliver arrive through the seams.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import autorun, delivery, desktop, guard, launch, logread, plan, tabs, verify

RETRY_PAUSE_SEC = 2  # breathe between the miss and the fresh resolve


@dataclass
class RunResult:
    """What one run answered: the kind, the message, the steps, the macro's log."""

    kind: str                 # ok | error | timeout | stopped | blocked | skipped
    message: str
    steps: tuple = ()
    lines: tuple = ()


def result_level(kind: str) -> str:
    """The log level one verdict kind deserves."""
    if kind == "ok":
        return "success"
    return "warn" if kind in ("timeout", "skipped") else "error"


def lines_of(outcomes) -> tuple:
    """Every run's log lines, headed by its label (the single run passes through)."""
    if len(outcomes) == 1:
        return tuple(outcomes[0][1].lines)
    rows = []
    for run, verdict in outcomes:
        rows.append(f"— run {run.index}/{run.total} ({run.label}) —")
        rows.extend(verdict.lines)
    return tuple(rows)


_VERDICT_PRIORITY = ("stopped", "blocked", "error", "timeout", "skipped")


def rollup(outcomes, total) -> tuple:
    """The sequence's kind: the worst verdict by priority, or ok when all answered."""
    kinds = [verdict.kind for _run, verdict in outcomes]
    for kind in _VERDICT_PRIORITY:
        if kind in kinds:
            return rollup_reason(kind, outcomes, total)
    return "ok", f"all {total} run(s) ok"


def rollup_reason(kind, outcomes, total) -> tuple:
    """The roll-up message for one non-ok priority kind (RULE 4: name the cause)."""
    first = next((run, verdict) for run, verdict in outcomes if verdict.kind == kind)
    if kind == "stopped":
        return "stopped", f"stopped after {len(outcomes)} of {total} run(s) — {first[1].message}"
    if kind == "blocked":
        skipped = total - len(outcomes)
        tail = f"; {skipped} run(s) not attempted" if skipped else ""
        return "blocked", f"{first[1].message}{tail}"
    if kind == "skipped":
        count = sum(1 for _run, verdict in outcomes if verdict.kind == "skipped")
        return "skipped", f"{count}/{total} run(s) skipped — {first[0].label}: {first[1].message}"
    ok = sum(1 for _run, verdict in outcomes if verdict.kind == "ok")
    return kind, f"{ok}/{total} run(s) ok — {first[0].label}: {first[1].message}"


def resolve_run_selector(run, rescan) -> tuple:
    """(selector, mapping-windows) — the title literal or a fresh tab=N (None = gone)."""
    if run.selector:
        return run.selector, plan.plan_window(list(run.target.windows), run.target.url)
    resolved = plan.resolve_selector(run, rescan())
    return resolved if resolved is not None else (None, [])


async def _nap(sleep_fn, seconds: float) -> None:
    """Best-effort pause — a refused sleep never fails the run (cancel re-raised)."""
    import asyncio
    try:
        await sleep_fn(seconds)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


class Sequence:
    """The planned runs in order; holds the run-wide state the steps share.

    A value object, not a god class: spec, seams, recorder, the provisioned
    page, the fresh-session reader and the protected-tab snapshot live here so
    every step stays at RULE 16's parameter budget.
    """

    def __init__(self, spec, seams, recorder):
        self.spec = spec
        self.seams = seams
        self.recorder = recorder
        self.page = ""
        self.rescan = tabs.profile_sessions  # fresh sessions per launch (runner overrides: seams)
        self.snapshot = {}                   # guard.snapshot_tabs at detect (runner sets it)

    def _stopped(self) -> bool:
        return bool(self.seams.stop and self.seams.stop())

    async def execute(self, runs: list):
        """Run every plan entry in order; stop between runs, abort on a refusal."""
        outcomes = []
        for pos, run in enumerate(runs):
            if self._stopped():
                return self._stopped_after(outcomes, len(runs))
            if pos > 0:
                await self._inter_run_delay()
            verdict = await self._one(run)
            outcomes.append((run, verdict))
            if len(runs) > 1:
                self.recorder("result", f"run {run.index}/{run.total} ({run.label}) — "
                                        f"{verdict.kind}: {verdict.message}",
                              result_level(verdict.kind))
            if verdict.kind in ("blocked", "stopped"):
                break
        return self._final(outcomes, len(runs))

    async def _inter_run_delay(self) -> None:
        """Wait between runs so Firefox can process the previous autostart tab."""
        delay = max(0, min(30, getattr(self.spec, "inter_run_delay_sec", 3)))
        if delay <= 0:
            return
        self.recorder("delay", f"waiting {delay}s before the next run "
                               f"(Firefox needs time to process the previous autostart tab)")
        await _nap(self.seams.sleep or _default_sleep, delay)

    async def _one(self, run):
        """One planned run: resolve → foreground → deliver → poll, one tab retry."""
        verdict = await _attempt_run(self, run, prime=True)
        if verdict is not None and logread.retryable(verdict) and not self._stopped():
            self.recorder("launch", f"{plan.run_scope(run)}tab not found — retrying once "
                                    f"with a fresh resolve", "warn")
            await _nap(self.seams.sleep or _default_sleep, RETRY_PAUSE_SEC)
            if self._stopped():
                return logread.LogResult(kind="stopped", message="stopped before the retry")
            logread.drop_log(run.log_path)
            verdict = await _attempt_run(self, run, prime=False)
        return verdict

        return f"run {run.index}/{run.total} ({run.label}): " if run.total > 1 else ""

    def _stopped_after(self, outcomes, total):
        """The user pressed Stop: name how much of the sequence actually ran."""
        if outcomes:
            last = outcomes[-1][1].message
            message = f"stopped after {len(outcomes)} of {total} run(s) — {last}"
        else:
            message = "stopped before the run began"
        self.recorder("result", f"stopped: {message}", "info")
        return RunResult(kind="stopped", message=message, steps=tuple(self.recorder.steps))

    def _final(self, outcomes, total):
        """One verdict for the sequence; a single run passes through unchanged."""
        for line, level in guard.verify_lines(self.snapshot, self.rescan):
            self.recorder("result", line, level)
        if total == 1:
            _run, verdict = outcomes[0]
            self.recorder("result", f"{verdict.kind}: {verdict.message}",
                          "info" if verdict.kind == "stopped" else result_level(verdict.kind))
            return RunResult(kind=verdict.kind, message=verdict.message,
                             steps=tuple(self.recorder.steps), lines=lines_of(outcomes))
        kind, message = rollup(outcomes, total)
        self.recorder("result", f"{kind}: {message}", result_level(kind))
        return RunResult(kind=kind, message=message, steps=tuple(self.recorder.steps),
                         lines=lines_of(outcomes))


async def _attempt_run(seq, run, prime: bool):
    """One delivery attempt: resolve the selector, foreground, deliver, poll."""
    selector, windows = resolve_run_selector(run, seq.rescan)
    if selector is None:
        seq.recorder("launch", f"{plan.run_scope(run)}skipped — the tab is no longer open "
                                f"(or its profile closed) since detect", "warn")
        return logread.LogResult(kind="skipped", message="the tab is no longer open")
    note = "" if run.selector else " (resolved fresh at launch)"
    seq.recorder("launch", f"{plan.run_scope(run)}addressing {selector}{note}")
    if prime:
        _foreground_run(seq, run)
    url = autorun.launch_url_for(seq.spec, seq.page, run, selector)
    return await _deliver_and_poll(seq, run, url, windows)

def _foreground_run(seq, run) -> None:
    """Raise the window holding this run's tab (critical rule: visible+front).

    The needle is the first non-blank pattern — a URL-only search maps the
    window through its URL (the session half of the mapping), a title
    pattern through both halves as before.
    """
    needle = (seq.spec.pattern or seq.spec.url_pattern or "").strip()
    windows = (seq.seams.windows() if seq.seams.windows
               else list(run.target.windows))
    mapped = desktop.foreground_tab_window(needle, windows)
    if mapped is not None:
        matches, raised = mapped
        titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
        seq.recorder("foreground", f"{plan.run_scope(run)}{raised}/{len(matches)} Firefox "
                                    f"window(s) on top — {titles} (holds the tab matching "
                                    f"“{needle}”)")
        return
    matches, raised = desktop.foreground(needle)
    if not matches:
        seq.recorder("foreground", f"{plan.run_scope(run)}no Firefox window matches "
                                    f"“{needle}” — launching anyway; the "
                                    f"macro reuses a matching tab and never opens one "
                                    f"(E210 if none)", "warn")
        return
    titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
    seq.recorder("foreground", f"{plan.run_scope(run)}{raised}/{len(matches)} Firefox "
                                f"window(s) on top — {titles}")

async def _deliver_and_poll(seq, run, url, windows):
    """The chosen delivery, then the savelog wait (timeouts get the autopsy)."""
    seen = seq.seams.os_windows() if seq.seams.os_windows else desktop.firefox_windows()
    kind, payload = desktop.choose_delivery(run, seen, run.total, windows)
    deadline = time.time() + float(seq.spec.timeout_sec)
    if kind == "addressbar":
        sent = _send_addressbar(seq, run, payload, url)
        if sent:
            handoff = verify.Delivery(hwnd=payload, url=url, deadline=deadline)
            return await verify.await_delivery(seq, run, handoff)
        return await verify.poll_to_deadline(seq, run, url, deadline)
    if kind == "cold":
        try:
            process = _cold_launch(seq, run, url)
        except OSError as exc:
            seq.recorder("launch", f"{plan.run_scope(run)}Firefox would not start: {exc}", "error")
            return logread.LogResult(kind="blocked",
                                     message=f"Firefox would not start: {exc}")
        if process is None:
            return logread.LogResult(kind="blocked",
                                     message="Firefox was not found — nothing was launched")
    else:
        for line, level in autorun.manual_lines(run, url, payload, seq.spec.timeout_sec):
            seq.recorder("launch", f"{plan.run_scope(run)}{line}", level)
    return await verify.poll_to_deadline(seq, run, url, deadline)

def _send_addressbar(seq, run, hwnd, url) -> bool:
    """Address-bar delivery; True when the keys went out (a refusal degrades)."""
    seq.recorder("launch", f"{plan.run_scope(run)}delivering the autorun URL into the "
                            f"profile's window (savelog={Path(run.log_path).name}, "
                            f"no new process)")
    send = seq.seams.deliver or delivery.deliver_url
    try:
        send(hwnd, url)
    except Exception as exc:
        seq.recorder("launch", f"{plan.run_scope(run)}address-bar delivery failed ({exc}) — "
                                f"open the URL below by hand instead", "warn")
        for line, level in autorun.manual_lines(run, url, "address-bar delivery failed",
                                                seq.spec.timeout_sec):
            seq.recorder("launch", f"{plan.run_scope(run)}{line}", level)
            return False
    seq.recorder("launch", f"{plan.run_scope(run)}delivered — waiting for the savelog file")
    return True

def _cold_launch(seq, run, url):
    """Resolve the binary and cold-start Firefox (missing binary → None)."""
    binary = launch.resolve_binary(seq.spec.binary)
    if not launch.binary_exists(binary):
        seq.recorder("launch", f"{plan.run_scope(run)}Firefox not found at {binary!r} — put its FULL path in "
                                f"the window's Firefox binary field (Firefox shortcut → "
                                f"Properties → Target, or `where firefox` in cmd); "
                                f"looked at: {'; '.join(launch.candidate_binaries())}",
                      "error")
        return None
    seq.recorder("launch", f"{plan.run_scope(run)}cold-starting Firefox with the autorun URL "
                            f"(macro={seq.spec.macro}, storage={seq.spec.storage}, "
                            f"savelog={Path(run.log_path).name})")
    process = launch.launch_resilient(launch.profile_argv(binary, url, run.profile_args),
                                      popen=seq.seams.popen)
    seq.recorder("launch", f"{plan.run_scope(run)}launched "
                            f"(pid {getattr(process, 'pid', '?')}) — waiting for the "
                            f"savelog file")
    return process

async def _default_sleep(seconds: float) -> None:
    """Real async sleep — the seam's default (tests inject a fast one)."""
    import asyncio
    await asyncio.sleep(seconds)

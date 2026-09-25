"""The planned runs, executed in order — re-check → foreground → launch → verify → poll.

One responsibility split out of the runner (2026-09-23, multi-profile fix;
re-armed 2026-09-24 for the tab-lifecycle rebuild): `Sequence.execute` walks
the `PlannedRun` list, honours Stop before every run and inside every poll
(RULE 7), and rolls the per-run verdicts up into ONE answer whose kinds stay
frozen — ok / error / timeout / stopped / blocked (RULE 4).

Two refusals mean different things (RULE 4 — never one invented "failed"):

* a **skipped** run (its profile stopped running, or its tab vanished before
  launch) is `blocked` WITHOUT `abort_rest` — the sequence moves on to the
  next profile; nothing was launched, so nothing was harmed;
* a **launch refusal** (the binary would not start) or a **mis-routed
  handoff** (the autorun tab landed in another profile) sets `abort_rest` —
  the same condition would bite every later run, so the sequence stops and
  says so.

No Qt, no bridge: report/stop/sleep/popen arrive through the seams; the
OS-side re-checks live in `TabChecks` and run only when no seam stands in
for the stores, so tests stay deterministic off a desktop.

One savelog error is rescored before it becomes a verdict (`rescore_cleanup_miss`):
a tab-not-found on the pinned autostart-tab locator can only happen AFTER every
work command succeeded (the macro stops at its first failure, and the cleanup
pair is pinned last) — the click fired, only the macro's own tab-close missed
its tab, and the page's backstop still closes it. The run answers ok, with the
miss named; every other error stays an error.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from . import autorun, desktop, launch, logread, plan, tabs

# How long one run waits for the autorun marker in the session stores before
# giving up the check (the savelog stays the verdict either way).
HANDOFF_WINDOW_SEC = 8.0


@dataclass
class RunResult:
    """What one run answered: the kind, the message, the steps, the macro's log."""

    kind: str                 # ok | error | timeout | stopped | blocked
    message: str
    steps: tuple = ()
    lines: tuple = ()


def run_scope(run) -> str:
    """The per-run prefix — only a multi-run sequence needs the numbering."""
    return f"run {run.index}/{run.total} ({run.label}): " if run.total > 1 else ""


def result_level(kind: str) -> str:
    """The log level one verdict kind deserves."""
    if kind == "ok":
        return "success"
    return "warn" if kind == "timeout" else "error"


def lines_of(outcomes) -> tuple:
    """Every run's log lines, headed by its label (the single run passes through)."""
    if len(outcomes) == 1:
        return tuple(outcomes[0][1].lines)
    rows = []
    for run, verdict in outcomes:
        rows.append(f"— run {run.index}/{run.total} ({run.label}) —")
        rows.extend(verdict.lines)
    return tuple(rows)


_VERDICT_PRIORITY = ("stopped", "blocked", "error", "timeout")


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
    ok = sum(1 for _run, verdict in outcomes if verdict.kind == "ok")
    return kind, f"{ok}/{total} run(s) ok — {first[0].label}: {first[1].message}"


# The extension's tab-not-found wording (E210/E212 — identical text in V9.6.1
# and V10, `src/ext/bg.js` PANEL_SELECT_WINDOW): the locator rides the message
# verbatim, so a miss on the pinned cleanup locator is recognisable in it.
TAB_NOT_FOUND = "failed to find the tab with locator '"


def rescore_cleanup_miss(verdict: logread.LogResult) -> logread.LogResult:
    """A not-found on the pinned autostart-tab locator means the work succeeded.

    The macro's last two commands are the cleanup pair (pinned in macro.py) and
    the macro stops at its FIRST failure — so this error can only follow a
    run where the tab select, the XClick and the echo all succeeded. Only the
    macro's own tab-close missed its tab (the extension did not match the
    title), and the page's backstop still closes it: the run's answer is ok,
    with the miss named instead of hidden. Every other error passes through —
    the work itself failed, and that stays an error.
    """
    if verdict.kind != "error" or TAB_NOT_FOUND not in verdict.message:
        return verdict
    if autorun.PAGE_TITLE_SELECTOR not in verdict.message:
        return verdict
    return logread.LogResult(
        kind="ok",
        message="macro completed — XClick fired; the macro's own tab-close "
                "missed the autostart tab (the extension did not match its "
                "title) — the page's backstop closes it shortly",
        lines=verdict.lines,
    )


async def _default_sleep(seconds: float) -> None:
    """Real async sleep — the seam's default (tests inject a fast one)."""
    await asyncio.sleep(seconds)


class TabChecks:
    """The real-path re-reads: before launch the run is re-verified, after it the
    handoff's landing is verified. A test seam standing in for the stores
    (`off`) makes every check a silent no-op, so fixtures stay deterministic.

    The pre-launch re-read is what the 2026-09-24 rebuild added: the profile's
    lock must still be alive, the store must still hold the run's tab, and a
    changed title rebuilds the selector from the FRESH full title (the store
    was just re-read — seconds old, not the detect-time snapshot).
    """

    def __init__(self, spec, seams, recorder):
        self.seams = seams
        self.recorder = recorder
        self.search = plan.Search(spec.pattern, spec.url_pattern)

    @property
    def off(self) -> bool:
        """True when a test seam stands in for the stores — the checks stand down."""
        return self.seams.profiles is not None or self.seams.tabs is not None

    def fresh_locator(self, run) -> str:
        """Right before launch, re-verify the run's tab; '' = go, else the skip reason."""
        if self.off or not run.target.profile_dir:
            return ""
        open_, _reason = tabs.profile_open(run.target.profile_dir)
        if not open_:
            return f"{run.label}: the profile is not running any more — skipped (nothing launched)"
        rows = tabs.tab_rows([Path(run.target.profile_dir)])
        fresh = self._fresh_title(rows, run)
        if not fresh:
            return (f"{run.label}: the tab {run.target.url[:90]} has no usable title any "
                    f"more (closed or titleless) — skipped (nothing launched)")
        if fresh != run.target.title:
            self._retitled(run, fresh)
        return ""

    @staticmethod
    def _fresh_title(rows, run) -> str:
        """The run's tab's current full title (exact URL match); '' when the row is gone."""
        for row in rows or []:
            if row.get("url") == run.target.url:
                return str(row.get("title", "")).strip()
        return ""

    def _retitled(self, run, fresh: str) -> None:
        """Rebuild this run's locator/label from the fresh title (the clip is gone)."""
        run.target = plan.retitled(run.target, fresh)
        run.selector = plan.selector_for(run.target, self.search)
        run.label = plan.run_label(run.target)
        self.recorder("launch", f"{run_scope(run)}the tab's title is now “{fresh[:60]}” "
                                f"— the locator was rebuilt from it")

    async def handoff_misrouted(self, run) -> logread.LogResult | None:
        """Did the autorun tab land in THIS run's profile? A wrong landing is named, not clicked.

        Evidence: the autorun marker (`ui.vision.html`) in the running profiles'
        stores. Marker in another profile → `-P` routing went astray (duplicate
        `profiles.ini Name=` entries make the handoff ambiguous) → `error` with
        `abort_rest` (every later run would land the same way). No marker in
        the window → proceed: the savelog remains the verdict.
        """
        if self.off or not run.target.profile_dir:
            return None
        window = float(getattr(self.seams, "handoff_window_sec", HANDOFF_WINDOW_SEC))
        deadline = time.time() + window
        while time.time() < deadline:
            await self._nap(1.0)
            seen = tabs.autorun_tab_seen()
            if seen.get(run.target.profile_dir):
                return None
            other = next((d for d in seen if d != run.target.profile_dir), "")
            if other:
                return self._misroute_verdict(run, other)
        return None

    def _misroute_verdict(self, run, other: str) -> logread.LogResult:
        """The mis-routed handoff as a verdict — both profiles named, the rest aborted."""
        want = plan.profile_label(run.target.profile_name, run.target.profile_dir) or "?"
        got = plan.profile_label("", other) or "?"
        message = (f"the handoff to profile “{want}” landed in profile “{got}” — duplicate "
                   f"profiles.ini Name= entries make the -P routing ambiguous; rename the "
                   f"profiles in Firefox's profile manager")
        self.recorder("handoff", f"{run_scope(run)}{message}", "error")
        return logread.LogResult(kind="error", message=message, abort_rest=True)

    async def _nap(self, seconds: float) -> None:
        """The injected sleep; only a cancellation may escape (RULE 7)."""
        sleep_fn = self.seams.sleep or _default_sleep
        try:
            await sleep_fn(seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


class Sequence:
    """The planned runs in order; holds the run-wide state the steps share.

    A value object, not a god class: spec, seams, recorder and the provisioned
    page live here so every step stays at RULE 16's parameter budget; the
    OS re-reads live in `TabChecks`.
    """

    def __init__(self, spec, seams, recorder):
        self.spec = spec
        self.seams = seams
        self.recorder = recorder
        self.page = ""
        self.checks = TabChecks(spec, seams, recorder)

    def _stopped(self) -> bool:
        return bool(self.seams.stop and self.seams.stop())

    async def execute(self, runs: list):
        """Run every plan entry in order; stop between runs, abort only on a refusal."""
        outcomes = []
        for pos, run in enumerate(runs):
            if self._stopped():
                return self._stopped_after(outcomes, len(runs))
            if pos > 0:
                await self._inter_run_delay()
            verdict = rescore_cleanup_miss(await self._one(run))
            outcomes.append((run, verdict))
            if len(runs) > 1:
                self.recorder("result", f"run {run.index}/{run.total} ({run.label}) — "
                                        f"{verdict.kind}: {verdict.message}",
                              result_level(verdict.kind))
            if verdict.kind == "stopped" or verdict.abort_rest:
                break
        return self._final(outcomes, len(runs))

    async def _inter_run_delay(self) -> None:
        """Wait between runs so Firefox can process the previous autostart tab."""
        delay = max(0, min(30, getattr(self.spec, "inter_run_delay_sec", 3)))
        if delay <= 0:
            return
        self.recorder("delay", f"waiting {delay}s before the next run "
                               f"(Firefox needs time to process the previous autostart tab)")
        sleep_fn = self.seams.sleep or _default_sleep
        try:
            await sleep_fn(delay)
        except Exception:
            pass

    async def _one(self, run) -> logread.LogResult:
        """One planned run end to end: re-check, raise its window, launch, verify, wait."""
        skip = self.checks.fresh_locator(run)
        if skip:
            self.recorder("launch", f"{run_scope(run)}{skip}", "warn")
            return logread.LogResult(kind="blocked", message=skip)
        self._foreground(run)
        try:
            process = self._launch(run)
        except OSError as exc:
            self.recorder("launch", f"Firefox would not start: {exc}", "error")
            return logread.LogResult(kind="blocked", message=f"Firefox would not start: {exc}",
                                     abort_rest=True)
        if process is None:
            return logread.LogResult(kind="blocked",
                                     message="Firefox was not found — nothing was launched",
                                     abort_rest=True)
        misrouted = await self.checks.handoff_misrouted(run)
        if misrouted is not None:
            return misrouted
        return await logread.poll_log(run.log_path,
                                      time.time() + float(self.spec.timeout_sec),
                                      sleep=self.seams.sleep, stop=self.seams.stop)

    def _foreground(self, run) -> None:
        """Raise the window holding this run's tab (critical rule: visible+front).

        The needle is the first non-blank pattern — a URL-only search maps the
        window through its URL (the session half of the mapping), a title
        pattern through both halves as before.
        """
        needle = (self.spec.pattern or self.spec.url_pattern or "").strip()
        windows = (self.seams.windows() if self.seams.windows
                   else list(run.target.windows))
        mapped = desktop.foreground_tab_window(needle, windows)
        if mapped is not None:
            matches, raised = mapped
            titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
            self.recorder("foreground", f"{run_scope(run)}{raised}/{len(matches)} Firefox "
                                        f"window(s) on top — {titles} (holds the tab matching "
                                        f"“{needle}”)")
            return
        matches, raised = desktop.foreground(needle)
        if not matches:
            self.recorder("foreground", f"{run_scope(run)}no Firefox window matches "
                                        f"“{needle}” — launching anyway; the "
                                        f"macro reuses a matching tab and never opens one "
                                        f"(E210 if none)", "warn")
            return
        titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
        self.recorder("foreground", f"{run_scope(run)}{raised}/{len(matches)} Firefox "
                                    f"window(s) on top — {titles}")

    def _launch(self, run):
        """Resolve the binary, build this run's official launch URL and start Firefox."""
        binary = launch.resolve_binary(self.spec.binary)
        if not launch.binary_exists(binary):
            self.recorder("launch", f"Firefox not found at {binary!r} — put its FULL path in "
                                    f"the window’s Firefox binary field (Firefox shortcut → "
                                    f"Properties → Target, or `where firefox` in cmd); "
                                    f"looked at: {'; '.join(launch.candidate_binaries())}",
                          "error")
            return None
        url = autorun.launch_url(autorun.LaunchSpec(
            page_path=str(self.page), macro=self.spec.macro, storage=self.spec.storage,
            log_path=run.log_path, pause_ms=self.spec.pause_ms,
            target=self.spec.target, tab=run.selector,
            backstop_sec=self.spec.timeout_sec + autorun.BACKSTOP_MARGIN_SEC))
        self.recorder("launch", f"{run_scope(run)}starting Firefox with the autorun URL "
                                f"(macro={self.spec.macro}, storage={self.spec.storage}, "
                                f"savelog={Path(run.log_path).name}, tab={run.selector})")
        process = launch.launch_resilient(launch.profile_argv(binary, url, run.profile_args),
                                          popen=self.seams.popen)
        self.recorder("launch", f"{run_scope(run)}launched "
                                f"(pid {getattr(process, 'pid', '?')}) — waiting for the "
                                f"savelog file")
        return process

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

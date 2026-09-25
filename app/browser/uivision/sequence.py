"""The planned runs, executed in order — foreground → launch → poll each.

One responsibility split out of the runner (2026-09-23, multi-profile fix):
`Sequence.execute` walks the `PlannedRun` list, honours Stop before every run
and inside every poll (RULE 7), aborts the rest when a launch is refused (the
same binary would refuse again) and rolls the per-run verdicts up into ONE
answer whose kinds stay frozen — ok / error / timeout / stopped / blocked
(RULE 4). A single-run sequence passes its verdict through unchanged, so the
pre-multi-profile behaviour, log lines and step sequence are preserved.
No Qt, no bridge: report/stop/sleep/popen arrive through the seams.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import autorun, desktop, launch, logread


@dataclass
class RunResult:
    """What one run answered: the kind, the message, the steps, the macro's log."""

    kind: str                 # ok | error | timeout | stopped | blocked
    message: str
    steps: tuple = ()
    lines: tuple = ()


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


class Sequence:
    """The planned runs in order; holds the run-wide state the steps share.

    A value object, not a god class: spec, seams, recorder and the provisioned
    page live here so every step stays at RULE 16's parameter budget.
    """

    def __init__(self, spec, seams, recorder):
        self.spec = spec
        self.seams = seams
        self.recorder = recorder
        self.page = ""

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
        sleep_fn = self.seams.sleep or _default_sleep
        try:
            await sleep_fn(delay)
        except Exception:
            pass

    async def _one(self, run) -> logread.LogResult:
        """One planned run end to end: raise its window, launch, wait for the verdict."""
        self._foreground(run)
        try:
            process = self._launch(run)
        except OSError as exc:
            self.recorder("launch", f"Firefox would not start: {exc}", "error")
            return logread.LogResult(kind="blocked", message=f"Firefox would not start: {exc}")
        if process is None:
            return logread.LogResult(kind="blocked",
                                     message="Firefox was not found — nothing was launched")
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
            self.recorder("foreground", f"{self._scope(run)}{raised}/{len(matches)} Firefox "
                                        f"window(s) on top — {titles} (holds the tab matching "
                                        f"“{needle}”)")
            return
        matches, raised = desktop.foreground(needle)
        if not matches:
            self.recorder("foreground", f"{self._scope(run)}no Firefox window matches "
                                        f"“{needle}” — launching anyway; the "
                                        f"macro reuses a matching tab and never opens one "
                                        f"(E210 if none)", "warn")
            return
        titles = "; ".join(title[:60] for _hwnd, title in matches[:3])
        self.recorder("foreground", f"{self._scope(run)}{raised}/{len(matches)} Firefox "
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
            target=self.spec.target, tab=run.selector))
        self.recorder("launch", f"{self._scope(run)}starting Firefox with the autorun URL "
                                f"(macro={self.spec.macro}, storage={self.spec.storage}, "
                                f"savelog={Path(run.log_path).name}, "
                                f"tab={launch_locator(self.spec.url_pattern, run.selector)})")
        process = launch.launch_resilient(launch.profile_argv(binary, url, run.profile_args),
                                          popen=self.seams.popen)
        self.recorder("launch", f"{self._scope(run)}launched "
                                f"(pid {getattr(process, 'pid', '?')}) — waiting for the "
                                f"savelog file")
        return process

    @staticmethod
    def _scope(run) -> str:
        """The per-run prefix — only a multi-run sequence needs the numbering."""
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


async def _default_sleep(seconds: float) -> None:
    """Real async sleep — the seam's default (tests inject a fast one)."""
    import asyncio
    await asyncio.sleep(seconds)


def launch_locator(url_pattern, selector: str) -> str:
    """The tab-locator story in the launch line: primary → hard fallback.

    With a TAB URL PATTERN the macro file opens with the guarded `url=*…*`
    attempt (today E209 → ignored, logged) and cmd_var3 carries the HARD
    `title=*…*` fallback that decides; without it the fallback alone is the
    whole story (2026-09-24 owner rule: show both).
    """
    url_pattern = (url_pattern or "").strip()
    if not url_pattern:
        return selector
    return f"url=*{url_pattern}* → {selector}"

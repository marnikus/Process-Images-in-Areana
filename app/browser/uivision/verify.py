"""Proof the autorun URL landed — and the autopsy when the macro stays silent.

SendInput reports success while the keys vanish (2026-09-24: focus loss, a
modal dialog, UIPI silence — no new tab, no savelog, a 90 s freeze). So the
run needs RECEIPT, layered cheapest-first: the foreground title a beat after
Enter (the new tab flips to the autostart page), then a bounded session-store
watch for this run's own savelog stamp in a tab URL, then ONE re-send when a
readable store proves the tab absent. Whatever still times out gets the
autopsy: open-but-silent and never-opened are different failures with
different checklists — plus the manual URL reprinted while still warm.

Imports point at leaves only (`autorun`, `delivery`, `logread`, `plan`,
`tabs`); `sequence`/`runner` call in, never the reverse.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from . import autorun, delivery, logread, plan, tabs

TITLE_RECEIPT_SEC = 1.5   # navigation beat before reading the foreground title
TAB_WATCH_SEC = 25        # one store flush (~15 s) + margin, then retry or fail


@dataclass(frozen=True)
class Delivery:
    """An addressed autorun handoff: where it went + when the wait ends."""

    hwnd: int
    url: str
    deadline: float       # the run's savelog deadline (an absolute time.time stamp)


def confirm_autorun_page(ops) -> bool:
    """True when the foreground window already shows the autostart page.

    After Enter the new tab's title flips to the page title — the fastest
    positive receipt. Anything unreadable answers False (the store watch is
    the backstop, never a false failure).
    """
    try:
        title = ops.foreground_title()
    except Exception:
        return False
    return "ui.vision" in str(title or "").lower()


def invocation_open(sessions, marker: str) -> bool:
    """True when a tab URL carries this run's savelog stamp (its own tab)."""
    for session in sessions or []:
        for row in session.get("rows") or []:
            if marker in str(row.get("url", "")):
                return True
    return False


def warn_addonless_profiles(targets, recorder) -> None:
    """Warn per target profile whose extensions.json lacks Ui.Vision (RULE 4).

    The global detect only knows SOME profile has the extension — a run aimed
    at an addon-less profile stalls on the autorun page (#204) every time.
    Unreadable stores stay silent (no guessing from silence).
    """
    seen = set()
    for target in targets or []:
        profile_dir = str(target.profile_dir or "")
        if not profile_dir or profile_dir in seen:
            continue
        seen.add(profile_dir)
        if tabs.addon_seen([profile_dir]) is False:
            who = plan.profile_label(target.profile_name, profile_dir)
            recorder("detect", f"profile “{who}”: no Ui.Vision in its extensions.json — "
                               f"runs there stall on the autorun page (#204)", "warn")


async def await_delivery(seq, run, handoff: Delivery):
    """The staged address-bar wait: fast receipt → watch → one re-send → verdict."""
    verdict = await _fast_stage(seq, run, handoff)
    if verdict is not None:
        return verdict
    verdict, state = await _watch_stage(seq, run, handoff)
    if verdict is not None:
        return verdict
    if state == "absent":
        _resend_once(seq, run, handoff)
        verdict, state = await _watch_stage(seq, run, handoff)
        if verdict is not None:
            return verdict
    return _missed_verdict(seq, run, handoff, state)


def report_timeout_autopsy(seq, run, url: str) -> None:
    """Name a savelog timeout: silent-tab and never-opened differ — say which.

    Lines only: the poll's verdict stands. The manual URL is reprinted while
    everything is still warm (reason + step; the wait line would lie now).
    """
    scope = plan.run_scope(run)
    state = _tab_state(seq, run)
    if state == "open":
        seq.recorder("launch", f"{scope}the autorun tab is open but the macro never "
                               f"answered — the page loaded and stalled", "warn")
        seq.recorder("launch", f"{scope}check: 'Allow access to file URLs' is ON for "
                               f"Ui.Vision (else Error #204); the macro name is case-exact",
                     "warn")
        seq.recorder("launch", f"{scope}check: the extension ran once by hand after install "
                               f"(first-run setup); the XModule home holds the macro", "warn")
    elif state == "unknown":
        seq.recorder("launch", f"{scope}no autorun tab seen — the session store stayed "
                               f"unreadable (Firefox may have closed)", "warn")
    else:
        seq.recorder("launch", f"{scope}no autorun tab opened — the keystrokes missed or "
                               f"the tab was closed", "warn")
        seq.recorder("launch", f"{scope}check: window focus, no modal dialogs, Ctrl+T opens "
                               f"a tab, Firefox not elevated", "warn")
    for line, level in autorun.manual_lines(run, url, "savelog wait expired",
                                            seq.spec.timeout_sec)[:2]:
        seq.recorder("launch", f"{scope}{line}", level)


async def _settle(sleep_fn, seconds: float) -> None:
    """Best-effort pause (a refused sleep never fails the run; cancel re-raised)."""
    import asyncio
    nap = sleep_fn or asyncio.sleep
    try:
        await nap(seconds)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


async def _bounded_poll(seq, run, deadline: float):
    """poll_log cut to `deadline` (the stage's own horizon, not the run's)."""
    return await logread.poll_log(run.log_path, deadline,
                                  sleep=seq.seams.sleep, stop=seq.seams.stop)


async def poll_to_deadline(seq, run, url: str, deadline: float):
    """The full savelog wait; a timeout gets the autopsy before returning."""
    verdict = await _bounded_poll(seq, run, deadline)
    if verdict.kind == "timeout":
        report_timeout_autopsy(seq, run, url)
    return verdict


async def _fast_stage(seq, run, handoff: Delivery):
    """Title receipt: the full wait when proven, else None (fall through)."""
    await _settle(seq.seams.sleep, TITLE_RECEIPT_SEC)
    ops = seq.seams.ops or delivery.Win32Ops()
    if confirm_autorun_page(ops):
        seq.recorder("launch", f"{plan.run_scope(run)}autorun page confirmed in the "
                               f"foreground — waiting for the macro")
        return await poll_to_deadline(seq, run, handoff.url, handoff.deadline)
    seq.recorder("launch", f"{plan.run_scope(run)}no autorun page in the foreground yet — "
                           f"watching the session store")
    return None


async def _watch_stage(seq, run, handoff: Delivery):
    """One bounded watch → (verdict-or-None, tab state for the re-send choice)."""
    verdict = await _bounded_poll(seq, run, min(handoff.deadline, time.time() + TAB_WATCH_SEC))
    if verdict.kind != "timeout":
        return verdict, None
    state = _tab_state(seq, run)
    if state == "open":
        seq.recorder("launch", f"{plan.run_scope(run)}autorun tab is open — the macro is "
                               f"slow or silent; waiting to the deadline")
        return await poll_to_deadline(seq, run, handoff.url, handoff.deadline), state
    return None, state


def _tab_state(seq, run) -> str:
    """"open" | "absent" | "unknown" — title (live) first, then the store."""
    ops = seq.seams.ops or delivery.Win32Ops()
    if confirm_autorun_page(ops):
        return "open"
    try:
        sessions = seq.rescan()
    except Exception:
        return "unknown"
    if sessions is None:
        return "unknown"
    marker = Path(run.log_path).name
    return "open" if invocation_open(sessions, marker) else "absent"


def _resend_once(seq, run, handoff: Delivery) -> None:
    """Re-send the keystrokes once (transient focus loss); degrade on refusal."""
    seq.recorder("launch", f"{plan.run_scope(run)}no autorun tab opened — re-sending the "
                           f"keystrokes once", "warn")
    send = seq.seams.deliver or delivery.deliver_url
    try:
        send(handoff.hwnd, handoff.url)
    except Exception as exc:
        seq.recorder("launch", f"{plan.run_scope(run)}re-send refused ({exc}) — the manual "
                               f"steps below still apply", "warn")
        for line, level in autorun.manual_lines(run, handoff.url, "re-send refused",
                                                seq.spec.timeout_sec):
            seq.recorder("launch", f"{plan.run_scope(run)}{line}", level)


def _missed_verdict(seq, run, handoff: Delivery, state: str):
    """The named miss: checklist lines + a timeout verdict that says so."""
    scope = plan.run_scope(run)
    if state == "unknown":
        seq.recorder("launch", f"{scope}no autorun tab seen — the session store stayed "
                               f"unreadable (Firefox may have closed)", "warn")
        message = "no autorun tab seen — the session store stayed unreadable"
    else:
        seq.recorder("launch", f"{scope}no autorun tab opened — the address-bar keystrokes "
                               f"missed the window", "warn")
        message = "no autorun tab opened — the address-bar keystrokes missed"
        seq.recorder("launch", f"{scope}check: the Firefox window holds the focus (click it, "
                               f"re-run); no modal dialogs block it; Ctrl+T opens a new tab",
                     "warn")
        seq.recorder("launch", f"{scope}check: Firefox is not elevated while the app runs "
                               f"normally (UIPI swallows the keys silently)", "warn")
    for line, level in autorun.manual_lines(run, handoff.url, "keystrokes missed",
                                            seq.spec.timeout_sec)[:2]:
        seq.recorder("launch", f"{scope}{line}", level)
    return logread.LogResult(kind="timeout", message=f"{message} (see the checklist above)")

"""Firefox job execution — one Ui.Vision macro run per dispatched job (design D-7).

The dispatcher's browser-agnostic claim hands a Firefox pool page here. The
machine runs ONE macro at a time (an asyncio lock cached on the bridge) with
the configured `firefox_auto.inter_run_delay_sec` gap after each run
(default 3 s, owner's §4.3); the target is the pool entry's OWN tab,
re-resolved by its stable id (a closed tab fails honestly — RULE 4, never a
launch at a stranger); the locator is the pool entry's URL as the guarded
`url=*…*` attempt baked into the macro file, with the tab's own title as the
hard `selectWindow` fallback (owner's §4.2); and the verdict comes from the
savelog through the existing `plan.runs`/`Sequence` executor. Stop (run
cancel or the row's Stop flag) is honoured in the gap and inside the poll
(RULE 7). No CDP, no captcha scope — this lane has no client (RULE 20
unchanged). Imports: browser + sibling services only, never `app.ui` (D-6).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Awaitable, Callable, Tuple

from app.browser.page_status import is_firefox
from app.browser.uivision import discovery, plan as uv_plan, runner as uv_runner
from app.browser.uivision.sequence import Sequence
from app.services.cooldown_service import is_tab_aborted
from app.services.firefox_config import build_spec, load_config

log = logging.getLogger("arena")

DEFAULT_GAP_SEC = 3.0      # the owner's §4.3 default when the config cannot answer
_GAP_SLICE_SEC = 0.5       # stop-aware sleep slice while waiting out the gap
_OK_KIND = "ok"


def _macro_lock(bridge):
    """The machine-wide 'one Ui.Vision macro at a time' lock (owner's §4.3)."""
    lock = getattr(bridge, "_ff_macro_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        bridge._ff_macro_lock = lock
    return lock


def _pending_gap(bridge, delay_sec: float, now: float | None = None) -> float:
    """Seconds this run still owes the previous one (0 for the first run)."""
    if delay_sec <= 0:
        return 0.0
    last_end = float(getattr(bridge, "_ff_last_run_end", 0.0) or 0.0)
    if last_end <= 0:
        return 0.0
    moment = time.monotonic() if now is None else now
    return min(delay_sec, max(0.0, delay_sec - (moment - last_end)))


def _gap_seconds(bridge) -> float:
    """The configured inter-run delay — one knob, read per job (owner's §4.3)."""
    try:
        return float(load_config(bridge).get("inter_run_delay_sec", DEFAULT_GAP_SEC))
    except Exception:
        return DEFAULT_GAP_SEC


async def _await_gap(bridge, delay_sec: float, stopped: Callable[[], bool]) -> None:
    """Wait out the inter-run delay in stop-aware slices (RULE 7)."""
    remaining = _pending_gap(bridge, delay_sec)
    while remaining > 0 and not stopped():
        await asyncio.sleep(min(_GAP_SLICE_SEC, remaining))
        remaining = _pending_gap(bridge, delay_sec)


def _stopped(bridge, pool, tab_id: str) -> bool:
    """Run cancel or this row's Stop button — the chrome predicates' twin."""
    if getattr(bridge, "_cancel_requested", False):
        return True
    try:
        return bool(is_tab_aborted(pool, tab_id))
    except Exception:
        return False


def _spec_for(bridge, page):
    """The validated config aimed at THIS pool entry's tab (owner's §4.2).

    The title filter is cleared on purpose: the stable id already chose the
    tab, and the locator becomes the pool entry's URL (guarded attempt) with
    the matched tab's own title as the hard fallback.
    """
    cfg = load_config(bridge)
    return replace(build_spec(bridge, cfg),
                   pattern="",
                   url_pattern=(page.url or cfg.get("url_pattern", "")),
                   selected_profiles=(page.profile,) if page.profile else ())


async def _find_target(page):
    """Re-resolve the pool entry's tab from the session store (executor — file reads)."""
    selected = (page.profile,) if page.profile else ()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, lambda: discovery.find_target(page.tab_id, selected=selected))


def _addressable(tab):
    """(tab, error) — selectWindow can only pick a titled, still-open tab (RULE 4)."""
    if tab is None:
        return None, "tab is no longer open in Firefox — nothing was launched"
    if not (tab.title or "").strip():
        return None, "tab has no title — selectWindow cannot address it"
    return tab, ""


def _target_for(tab) -> uv_plan.Target:
    """The discovered tab as the executor's Target (windows ride along)."""
    return uv_plan.Target(profile_name=tab.profile_name, profile_dir=tab.profile_dir,
                          url=tab.url, title=tab.title, windows=tuple(tab.windows or ()))


def _reporter(bridge) -> Callable[..., None]:
    """RULE 2: every macro step reaches the log console, tagged as a job."""
    def report(step: str, message: str, level: str = "info") -> None:
        try:
            bridge._log(f"🦊 job {step}: {message}", level)
        except Exception:
            pass
    return report


def _seams(stopped: Callable[[], bool]) -> uv_runner.RunSeams:
    """Runner seams: stop is wired; sleep/popen stay real (tests replace this)."""
    return uv_runner.RunSeams(stop=stopped)


async def _execute(bridge, spec, target, stopped: Callable[[], bool]):
    """provision → one PlannedRun → Sequence verdict (the single testable choke)."""
    recorder = uv_runner.Recorder(_reporter(bridge))
    page_path = uv_runner.provision(spec, recorder)
    runs = uv_plan.runs([target], uv_plan.Patterns(spec.pattern, spec.url_pattern),
                        spec.config_dir, time.strftime("%Y%m%d-%H%M%S"))
    executor = Sequence(spec, _seams(stopped), recorder)
    executor.page = str(page_path)
    return await executor.execute(runs)


def _verdict(result) -> Tuple[bool, str]:
    """(failed, error): ok is success; every other frozen kind names itself (RULE 4)."""
    if result.kind == _OK_KIND:
        return False, ""
    return True, f"{result.kind}: {result.message}"


async def run_macro_job(bridge, pool, tab_id: str) -> Tuple[bool, str]:
    """One dispatched image job on a Firefox pool page — the ff lane of both dispatchers.

    Serialised machine-wide with the configured gap (owner's §4.2). Unexpected
    exceptions propagate — the dispatcher's record path already turns a crash
    into a failed image with the traceback in the log.
    """
    page = pool.get_page(tab_id) if pool is not None else None
    if page is None or not is_firefox(page):
        return True, "tab left the pool before the macro ran"
    async with _macro_lock(bridge):
        try:
            return await _run_locked(bridge, pool, tab_id, page)
        except (ValueError, OSError) as exc:
            return True, f"blocked: {exc}"
        finally:
            bridge._ff_last_run_end = time.monotonic()


async def _run_locked(bridge, pool, tab_id: str, page) -> Tuple[bool, str]:
    """Gap → stop → resolve → execute → verdict, under the machine-wide lock."""
    stopped = lambda: _stopped(bridge, pool, tab_id)
    await _await_gap(bridge, _gap_seconds(bridge), stopped)
    if stopped():
        return True, "stopped: cancelled before the macro ran"
    tab, error = _addressable(await _find_target(page))
    if tab is None:
        return True, error
    result = await _execute(bridge, _spec_for(bridge, page),
                            _target_for(tab), stopped)
    return _verdict(result)

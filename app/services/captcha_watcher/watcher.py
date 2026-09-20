"""CaptchaWatcher — dedicated solve loop, independent of the job pipeline.

Every TICK_SEC the loop asks its `tabs` provider for the app-owned pages,
evaluates detect.js on each, and — when a solvable reCAPTCHA challenge is
on screen — submits it through `SdkSolver` and injects the token with
inject.js. Nothing else in the app solves captchas (see package docstring).

Behavioural guards (money + politeness):
* MAX_SOLVE_ATTEMPTS per tab per encounter; the budget resets once the
  challenge disappears from that tab (a fresh challenge is a fresh budget).
* one solve at a time (a solve blocks the tick; other tabs are scanned on
  the next tick) — sequential, observable, bounded.
* EVAL_TIMEOUT_SEC on every page evaluation so a hung tab cannot stall the
  loop; all failures are logged and fail open (RULE 9).
* the loop never touches a page the pipeline is not already attached to
  (RULE 20: user-authorised URLs only) — the provider decides the set.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from . import probes
from .sdk_solver import SdkSolver, sdk_available
from .signals import CaptchaSignal, SolveResult, WatcherStatus

log = logging.getLogger("arena")

TICK_SEC = 4.0
MAX_SOLVE_ATTEMPTS = 2
EVAL_TIMEOUT_SEC = 8.0


@dataclass
class WatcherDeps:
    """Seams the panel injects (keeps the watcher Qt-free and testable)."""

    tabs: Callable[[], Any]                              # → List[{"id", "url"}] (sync or awaitable)
    evaluate: Callable[[str, str], Awaitable[Any]]       # (tab_id, js) → value or None
    solver_factory: Callable[[], Optional[SdkSolver]]    # reads the key file at call time
    log: Callable[[str, str], None] = lambda m, l="info": log.info(m)
    on_status: Optional[Callable[[Dict[str, Any]], None]] = None


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, asyncio.Future):
        return await value
    return value


def _tab_fields(tab: Any) -> tuple[str, str]:
    """(id, url) from a dict or an object with id/tab_id + url attrs."""
    if isinstance(tab, dict):
        return str(tab.get("id") or tab.get("tab_id") or ""), str(tab.get("url") or "")
    tid = getattr(tab, "tab_id", "") or getattr(tab, "id", "")
    return str(tid or ""), str(getattr(tab, "url", "") or "")


def _safe_log(deps: WatcherDeps, msg: str, level: str = "info") -> None:
    try:
        deps.log(msg, level)
    except Exception:
        pass


async def _eval(deps: WatcherDeps, status: WatcherStatus, tab_id: str, js: str) -> Any:
    """Bounded page evaluation; any failure → None + last_error (fail open)."""
    try:
        return await asyncio.wait_for(deps.evaluate(tab_id, js), timeout=EVAL_TIMEOUT_SEC)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        status.last_error = f"eval {tab_id[:12]}: {exc}"[:200]
        return None


class _Encounter:
    """One tab's solve → inject attempt (kept out of CaptchaWatcher for RULE 16 size)."""

    def __init__(self, deps: WatcherDeps, status: WatcherStatus):
        self._deps = deps
        self._status = status

    async def run(self, tab_id: str, signal: CaptchaSignal, solver: SdkSolver) -> bool:
        self._status.solving_tab = tab_id
        result = await solver.solve(signal)
        self._status.solving_tab = ""
        if not result.ok:
            return self._fail(tab_id, result)
        inj = await _eval(self._deps, self._status, tab_id, probes.inject_js(result.token, signal.sitekey))
        if not probes.inject_ok(inj):
            return self._fail(tab_id, SolveResult(ok=False, task_id=result.task_id,
                                                  error=f"inject failed: {probes.inject_summary(inj)}"))
        self._status.solved_total += 1
        self._status.last_solved_at = time.time()
        self._status.last_error = ""
        _safe_log(self._deps, f"✅ Captcha Watcher: solved {tab_id[:12]} in {result.elapsed_s:.0f}s "
                              f"— inject {probes.inject_summary(inj)}", "success")
        return True

    def _fail(self, tab_id: str, result: SolveResult) -> bool:
        self._status.failed_total += 1
        self._status.last_error = result.error[:200]
        _safe_log(self._deps, f"❌ Captcha Watcher: solve failed on {tab_id[:12]} — {result.error}", "error")
        return False


class CaptchaWatcher:
    """Start/stop-able solve loop; one instance per Bridge."""

    def __init__(self, deps: WatcherDeps, tick_sec: float = TICK_SEC):
        self._deps = deps
        self._tick = max(1.0, float(tick_sec or TICK_SEC))
        self._status = WatcherStatus(sdk_available=sdk_available())
        self._encounter = _Encounter(deps, self._status)
        self._attempts: Dict[str, int] = {}
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop = False

    # ---- lifecycle -------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self._status.running)

    def status(self) -> Dict[str, Any]:
        solver = self._solver()
        self._status.has_key = bool(solver and solver.has_key)
        self._status.sdk_available = sdk_available()
        return self._status.to_dict()

    async def run_forever(self) -> None:
        """Loop body — schedule on the bg loop; returns when stop() is called."""
        if self._status.running:
            return
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        self._stop = False
        self._status.running = True
        self._log(f"🛡️ Captcha Watcher ON — scanning every {self._tick:g}s (SDK solver only)", "success")
        self._emit()
        try:
            while not self._stop:
                await self._safe_tick()
                await asyncio.sleep(self._tick)
        except asyncio.CancelledError:
            pass
        finally:
            self._status.running = False
            self._status.solving_tab = ""
            self._task = None
            # Do not emit a captcha-labelled log on shutdown.  OFF is a
            # hard boundary: subsequent ticks are silent until explicitly
            # started again.
            self._emit()

    def stop(self) -> None:
        """Thread-safe stop request (cancels the loop task on its own loop)."""
        self._stop = True
        task, loop = self._task, self._loop
        if task is None or loop is None:
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except Exception:
            pass

    # ---- one tick --------------------------------------------------------
    async def _safe_tick(self) -> None:
        try:
            await self.tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._status.last_error = str(exc)[:200]
            self._log(f"Captcha Watcher tick failed: {exc}", "warn")

    async def tick(self) -> int:
        """Scan every provided tab once; returns the number of tabs scanned."""
        tabs = list(await _maybe_await(self._deps.tabs()) or [])
        self._status.ticks += 1
        self._status.tabs_seen = len(tabs)
        self._status.touch()
        seen: List[str] = []
        for tab in tabs:
            tab_id, url = _tab_fields(tab)
            if not tab_id:
                continue
            seen.append(tab_id)
            await self._scan_tab(tab_id, url)
        self._attempts = {k: v for k, v in self._attempts.items() if k in seen}
        self._emit()
        return len(seen)

    async def _scan_tab(self, tab_id: str, url: str) -> None:
        res = await _eval(self._deps, self._status, tab_id, probes.detect_js())
        signal = CaptchaSignal.from_result(res, url)
        if not signal.visible:
            self._attempts.pop(tab_id, None)   # challenge gone → fresh budget next time
            return
        if not signal.solvable:
            self._log(f"Captcha Watcher: {signal.kind or 'unknown'} captcha on {tab_id[:12]} "
                      f"is not SDK-solvable (sitekey={'set' if signal.sitekey else 'missing'})", "warn")
            return
        if self._attempts.get(tab_id, 0) >= MAX_SOLVE_ATTEMPTS:
            return
        solver = self._solver()
        if solver is None or not solver.has_key:
            self._status.last_error = "no 2Captcha API key"
            return
        self._attempts[tab_id] = self._attempts.get(tab_id, 0) + 1
        self._log(f"🤖 Captcha Watcher: solving {signal.kind} on {tab_id[:12]} "
                  f"(attempt {self._attempts[tab_id]}/{MAX_SOLVE_ATTEMPTS})", "warn")
        await self._encounter.run(tab_id, signal, solver)

    # ---- seams -----------------------------------------------------------
    def _solver(self) -> Optional[SdkSolver]:
        try:
            return self._deps.solver_factory()
        except Exception as exc:
            self._status.last_error = f"solver: {exc}"[:200]
            return None

    def _emit(self) -> None:
        if self._deps.on_status is None:
            return
        try:
            self._deps.on_status(self.status())
        except Exception:
            pass

    def _log(self, msg: str, level: str = "info") -> None:
        _safe_log(self._deps, msg, level)

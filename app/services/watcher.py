"""Watcher service — passively rechecks every x ms if page has awaiting icon (generating) or captcha.

In both situations it draws rectangle msg on left center page with msg "wait for finish generation"
or "wait for user. Captcha" and sleeps circle run and waits it solve.

Time to solve timeout is user configurable in win settings.
"""

import asyncio
import time
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field

log = logging.getLogger("watcher")

@dataclass
class WatcherConfig:
    enabled: bool = False
    check_interval_ms: int = 2000  # every x ms
    captcha_timeout_sec: int = 300  # 5 min default for user to solve captcha
    generation_timeout_sec: int = 600  # 10 min for generation to finish
    auto_pause_jobs: bool = True  # pause job runner when watcher triggers

@dataclass
class WatcherState:
    status: str = "idle"  # idle, watching, waiting_generation, waiting_captcha, paused
    last_check: float = 0
    last_generation_details: Dict[str, Any] = field(default_factory=dict)
    last_captcha_detected: bool = False
    waiting_since: Optional[float] = None
    waiting_kind: Optional[str] = None  # generation or captcha
    checks_count: int = 0
    generation_waits: int = 0
    captcha_waits: int = 0


class WatcherService:
    """Passive watcher that checks page state every interval."""

    def __init__(self, config: WatcherConfig = None, cdp_controller_getter: Callable = None, job_runner_getter: Callable = None, logger: Callable = None):
        self.config = config or WatcherConfig()
        self.state = WatcherState()
        self._cdp_getter = cdp_controller_getter  # function that returns controller or None
        self._job_runner_getter = job_runner_getter
        self._logger = logger or (lambda msg, level="info": log.info(msg))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._callbacks = []  # list of async callbacks for state changes

    def set_cdp_getter(self, getter: Callable):
        self._cdp_getter = getter

    def set_job_runner_getter(self, getter: Callable):
        self._job_runner_getter = getter

    def set_logger(self, logger: Callable):
        self._logger = logger

    def update_config(self, **kwargs):
        """Update watcher config from UI win settings."""
        for k, v in kwargs.items():
            if hasattr(self.config, k):
                setattr(self.config, k, v)
        self._logger(f"Watcher config updated: interval={self.config.check_interval_ms}ms captcha_timeout={self.config.captcha_timeout_sec}s gen_timeout={self.config.generation_timeout_sec}s enabled={self.config.enabled}", "info")
        # If enabled changed, start/stop
        if self.config.enabled and not self._running:
            self.start()
        elif not self.config.enabled and self._running:
            self.stop()

    def get_config(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "check_interval_ms": self.config.check_interval_ms,
            "captcha_timeout_sec": self.config.captcha_timeout_sec,
            "generation_timeout_sec": self.config.generation_timeout_sec,
            "auto_pause_jobs": self.config.auto_pause_jobs,
        }

    def get_state(self) -> Dict[str, Any]:
        return {
            "status": self.state.status,
            "last_check": self.state.last_check,
            "last_check_human": time.strftime("%H:%M:%S", time.localtime(self.state.last_check)) if self.state.last_check else "never",
            "checks_count": self.state.checks_count,
            "generation_waits": self.state.generation_waits,
            "captcha_waits": self.state.captcha_waits,
            "waiting_since": self.state.waiting_since,
            "waiting_kind": self.state.waiting_kind,
            "waiting_duration": int(time.time() - self.state.waiting_since) if self.state.waiting_since else 0,
            "last_generation_details": self.state.last_generation_details,
            "last_captcha_detected": self.state.last_captcha_detected,
        }

    def add_callback(self, cb: Callable):
        """Add callback for state changes — cb(state_dict)"""
        self._callbacks.append(cb)

    async def _notify(self):
        state = self.get_state()
        config = self.get_config()
        payload = {**state, "config": config}
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(payload)
                else:
                    cb(payload)
            except Exception as e:
                log.debug(f"Watcher callback failed: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self.state.status = "watching"
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._loop())
        except RuntimeError:
            # No running loop in test context — defer task creation
            # The bridge will call start again when event loop is running
            self._task = None
        self._logger(f"👁️ Watcher started — checking every {self.config.check_interval_ms}ms", "success")

    def ensure_task(self):
        """Ensure background task is running if enabled and loop available — call from bridge when loop ready."""
        if not self.config.enabled:
            return
        if self._task and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            if not self._running:
                self._running = True
                self.state.status = "watching"
            self._task = loop.create_task(self._loop())
            self._logger(f"👁️ Watcher task ensured — interval {self.config.check_interval_ms}ms", "info")
        except RuntimeError:
            pass

    def stop(self):
        self._running = False
        self.state.status = "idle"
        if self._task:
            self._task.cancel()
            self._task = None
        self._logger("👁️ Watcher stopped", "warn")

    async def _loop(self):
        """Main loop — every x ms check page."""
        try:
            while self._running:
                try:
                    await self.check_once()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self._logger(f"Watcher check failed: {e}", "error")
                    log.exception("Watcher loop error")
                # Sleep interval
                await asyncio.sleep(self.config.check_interval_ms / 1000.0)
        except asyncio.CancelledError:
            pass
        finally:
            self.state.status = "idle"

    async def check_once(self) -> Dict[str, Any]:
        """Single check — returns state."""
        self.state.checks_count += 1
        self.state.last_check = time.time()

        cdp = self._cdp_getter() if self._cdp_getter else None
        if not cdp:
            # No CDP controller — idle
            self.state.status = "watching"
            await self._notify()
            return self.get_state()

        # Check captcha first — higher priority
        try:
            is_captcha = await cdp.is_security_dialog_visible()
        except Exception as e:
            is_captcha = False
            self._logger(f"Watcher captcha check error: {e}", "warn")

        self.state.last_captcha_detected = is_captcha

        if is_captcha:
            # Captcha detected — draw rectangle and wait + apply cooldown penalty per tab
            if self.state.waiting_kind != "captcha":
                self.state.waiting_since = time.time()
                self.state.waiting_kind = "captcha"
                self.state.captcha_waits += 1
                self.state.status = "waiting_captcha"
                self._logger(f"🛡️ Watcher: Captcha detected — drawing rectangle 'wait for user. Captcha' on left center (timeout {self.config.captcha_timeout_sec}s user setting from win), pausing jobs + applying cooldown penalty per tab", "warn")
                # Show overlay with timeout from win settings
                try:
                    await cdp.show_watcher_overlay("wait for user. Captcha", kind="captcha", timeout_sec=self.config.captcha_timeout_sec, elapsed_sec=0)
                except Exception as e:
                    self._logger(f"Watcher overlay show failed: {e}", "warn")
                # Apply captcha penalty per tab (Job Cycle & Cooldown Logic)
                try:
                    await self._apply_captcha_penalty_for_current_tab()
                except Exception as e:
                    self._logger(f"Captcha penalty apply failed: {e}", "warn")
                # Pause jobs if configured
                if self.config.auto_pause_jobs:
                    jr = self._job_runner_getter() if self._job_runner_getter else None
                    if jr and hasattr(jr, 'pause_run'):
                        try:
                            jr.pause_run()
                        except Exception:
                            pass
                await self._notify()
            else:
                # Already waiting — check timeout
                elapsed = time.time() - (self.state.waiting_since or time.time())
                if elapsed > self.config.captcha_timeout_sec:
                    self._logger(f"⏰ Watcher: Captcha wait timeout after {int(elapsed)}s (limit {self.config.captcha_timeout_sec}s) — still waiting, user needs to solve", "error")
                    # Don't auto-resume, keep waiting but log timeout — user setting is max wait, but we keep waiting?
                    # Per spec: time to solve timeout add user in win — so we respect timeout but keep overlay
                    # We will continue waiting until solved, but notify timeout
                    await self._notify()
                else:
                    # Still waiting
                    pass

            # Sleep circle — wait loop: check again after interval, but stay in waiting state
            # The main loop will re-check after interval
            return self.get_state()

        # Check generating (awaiting icon)
        try:
            is_gen, gen_details = await cdp.is_generating()
        except Exception as e:
            is_gen = False
            gen_details = {"error": str(e)}

        self.state.last_generation_details = gen_details

        if is_gen:
            if self.state.waiting_kind != "generation":
                self.state.waiting_since = time.time()
                self.state.waiting_kind = "generation"
                self.state.generation_waits += 1
                self.state.status = "waiting_generation"
                details_str = ", ".join([d.get("label","") for d in gen_details.get("details", [])]) if isinstance(gen_details, dict) else ""
                self._logger(f"⏳ Watcher: Generation detected {details_str} — drawing rectangle 'wait for finish generation' on left center (timeout {self.config.generation_timeout_sec}s user setting from win), pausing jobs", "warn")
                try:
                    await cdp.show_watcher_overlay("wait for finish generation", kind="generation", timeout_sec=self.config.generation_timeout_sec, elapsed_sec=0)
                except Exception as e:
                    self._logger(f"Watcher overlay show failed: {e}", "warn")
                if self.config.auto_pause_jobs:
                    jr = self._job_runner_getter() if self._job_runner_getter else None
                    if jr and hasattr(jr, 'pause_run'):
                        try:
                            jr.pause_run()
                        except Exception:
                            pass
                await self._notify()
            else:
                elapsed = time.time() - (self.state.waiting_since or time.time())
                if elapsed > self.config.generation_timeout_sec:
                    self._logger(f"⏰ Watcher: Generation wait timeout after {int(elapsed)}s (limit {self.config.generation_timeout_sec}s) — still generating, keep waiting", "error")
                    await self._notify()

            return self.get_state()

        # No captcha, no generation — if we were waiting, clear overlay and resume
        if self.state.waiting_kind in ("generation", "captcha"):
            kind = self.state.waiting_kind
            elapsed = int(time.time() - (self.state.waiting_since or time.time()))
            self._logger(f"✅ Watcher: {kind} finished after {elapsed}s — clearing overlay, resuming", "success")
            try:
                await cdp.hide_watcher_overlay()
            except Exception:
                pass
            # Resume jobs if paused by watcher
            if self.config.auto_pause_jobs:
                jr = self._job_runner_getter() if self._job_runner_getter else None
                if jr and hasattr(jr, 'resume_run'):
                    try:
                        jr.resume_run()
                    except Exception:
                        pass
            self.state.waiting_since = None
            self.state.waiting_kind = None
            self.state.status = "watching"
            await self._notify()

        else:
            self.state.status = "watching"

        await self._notify()
        return self.get_state()

    def _get_bridge(self):
        try:
            return self._job_runner_getter() if self._job_runner_getter else None
        except Exception:
            return None

    def _get_current_tab_id(self):
        try:
            cdp = self._cdp_getter() if self._cdp_getter else None
            if not cdp:
                return None
            client = getattr(cdp, "cdp", None)
            if client and hasattr(client, "_current_tab_id"):
                return client._current_tab_id
        except Exception:
            pass
        return None

    def _find_url_for_penalty(self, bridge, tab_id):
        try:
            urls = getattr(bridge.state, "urls", []) if hasattr(bridge, "state") else []
            pool = getattr(bridge, "_page_pool", None)
            page_url = ""
            if pool and tab_id:
                try:
                    pg = pool.get_page(tab_id)
                    page_url = getattr(pg, "url", "") if pg else ""
                except Exception:
                    pass
            if page_url:
                for u in urls:
                    if page_url in u.url or u.url in page_url:
                        return u
            for u in urls:
                if u.enabled:
                    return u
        except Exception:
            pass
        return None

    async def _apply_captcha_penalty_for_current_tab(self):
        try:
            bridge = self._get_bridge()
            if not bridge:
                return
            tab_id = self._get_current_tab_id()
            url_row = self._find_url_for_penalty(bridge, tab_id)
            from app.services.job_cycle_service import JobCycleCtx, handle_captcha_detected_cycle

            ctx = JobCycleCtx(bridge=bridge, pool=getattr(bridge, "_page_pool", None), tab_id=tab_id or "", url_row=url_row)
            await handle_captcha_detected_cycle(ctx)
            self._logger(f"🛡️ Captcha penalty applied per tab {tab_id[:12] if tab_id else 'primary'} +15 min stack", "warn")
        except Exception as e:
            self._logger(f"Penalty helper failed {e}", "warn")

    async def force_clear(self):
        """Force clear overlay and reset waiting state."""
        cdp = self._cdp_getter() if self._cdp_getter else None
        if cdp:
            try:
                await cdp.hide_watcher_overlay()
            except Exception:
                pass
        self.state.waiting_since = None
        self.state.waiting_kind = None
        self.state.status = "watching"
        await self._notify()
        self._logger("Watcher overlay cleared manually", "info")

"""Bridge — QWebChannel QObject exposing slots to JS.

Handles:
- layout persistence (grid_layout, window_states)
- theme
- window presets (save/load/list/delete/import/export with preview)
- arena operations (urls, folder, queue, prompt, settings, run controls, highlight)
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.ui.qt_compat import QObject, Signal, Slot

from app.core.layout_service import (
    canonical_grid_payload, default_payload,
)
from app.core.models import AppState
from app.core.persistence import load_state
from app.core.scanner import scan_folder
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService
from app.browser.dom_highlight import build_highlight_js, build_clear_js, build_highlight_probe, build_find_probe, build_click_probe
from app.browser.probe_requests import FindProbeSpec, ClickProbeSpec, HighlightSpec, COLOR_FIND, COLOR_CLICK, COLOR_COLLECT
from app.browser.visual_click import ClickRequest, find_and_click
from app.ui.panels import blocks_stack, layout_state
from app.ui.panels.queue_scan import push_queue_undo, selected_images
from app.ui.panels.watcher_captcha import (
    captcha_service, get_watcher_cdp_controller, on_watcher_state)
from app.services.run_state import persist_cooldowns
from app.ui.panels.url_queue import (
    _URL_GATE_MSG,
    _add_missing_rows,
    _checked_tabs_ready,
    _dedupe_state_rows,
    _tab_already_owned,
    _urls_gate_error,
    enabled_urls,
)  # compat: single source lives in panels/url_queue.py
from app.ui.panels.layout_state import LayoutStateMixin
from app.ui.panels.blocks_library import BlocksLibraryMixin
from app.ui.panels.blocks_stack import BlocksStackMixin
from app.ui.panels.undo_history import UndoHistoryMixin
from app.ui.panels.url_queue import UrlQueueMixin
from app.ui.panels.queue_scan import QueueScanMixin
from app.ui.panels.app_settings import AppSettingsMixin
from app.ui.panels.watcher_captcha import WatcherCaptchaMixin
from app.ui.panels.page_pool import PagePoolMixin
from app.ui.panels.browser_tabs import BrowserTabsMixin
from app.ui.services import arena_serialize, undo_entries
from app.core.action_blocks import (
    default_stack,
    stack_to_dicts,
)

log = logging.getLogger("arena")


# ── URL-row ownership helpers (I-33) — module level, keep Bridge slim ──








class Bridge(QObject, LayoutStateMixin, BlocksLibraryMixin, BlocksStackMixin, UndoHistoryMixin, UrlQueueMixin, QueueScanMixin, AppSettingsMixin, WatcherCaptchaMixin, PagePoolMixin, BrowserTabsMixin):
    log_message = Signal(str, str)
    grid_layout_changed = Signal(str)
    grid_layout_persisted = Signal(bool)
    window_preset_list_updated = Signal(str)
    arena_log = Signal(str, str)
    arena_state_updated = Signal(str)
    progress_updated = Signal(str)
    highlight_rect = Signal(str)
    history_changed = Signal()
    undo_state_changed = Signal(str)  # JSON {history,index,canUndo,canRedo}
    tabs_received = Signal(str)
    connection_status = Signal(str)
    tab_match_result = Signal(str, str)
    url_presets_updated = Signal(str)
    presets_changed = Signal(str, str)  # kind, payload
    action_blocks_updated = Signal(str)  # JSON array of blocks
    job_action_status = Signal(str, str, str)  # jobId, blockId, statusJson
    job_started = Signal(str, str)  # jobId, imagePath
    job_finished = Signal(str, str)  # jobId, resultJson
    watcher_status = Signal(str)  # JSON status
    watcher_log = Signal(str, str)  # msg, level
    page_pool_updated = Signal(str)  # JSON snapshot steady/busy
    thumbnail_ready = Signal(str, str)  # img_id, payload_json — non-blocking thumb

    def __init__(self, config_manager: ConfigManager, state_path: Path, cdp_client=None, parent=None):
        super().__init__(parent)
        self.config = config_manager
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self._run_state = "idle"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._exported_paths = {}
        self.undo_service = UndoService(self.config.undo)
        self.cdp = cdp_client
        # persistent bg loop for CDP (keeps websocket alive)
        import threading as _th
        self._bg_loop = None
        self._bg_thread = None
        self._bg_lock = _th.Lock()
        self._bg_ready = _th.Event()
        # debouncing for CDP tab find/connect to avoid x2 logs and race
        self._last_find_query = ""
        self._last_find_ts = 0.0
        self._last_connect_ws = ""
        self._last_connect_ts = 0.0
        self._find_in_progress = False
        self._connect_in_progress = False
        self._auto_scan_running = False
        self._ensure_running = False
        self._persist_ok = True
        self._restore_note_done = False
        # thumbnail cache + thread pool to avoid UI freeze on mouse clicks
        # Previously get_image_thumbnail did PIL thumbnail sync in main thread for 80 images -> freeze
        self._thumb_cache = {}
        self._thumb_in_progress = set()
        try:
            import concurrent.futures as _cf
            self._thumb_executor = _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
        except Exception:
            self._thumb_executor = None
        # scan folder debouncing to avoid freeze
        self._scan_in_progress = False
        # ensure undo history loaded
        try:
            self.config.undo.load()
        except Exception:
            pass
        # install CDP status forwarding if client exists
        if self.cdp:
            try:
                self.cdp.connected.connect(lambda: self.connection_status.emit("connected"))
                self.cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
                self.cdp.error.connect(lambda e: self._on_cdp_error(e))
            except Exception:
                pass

        # Watcher service — passive recheck every x ms for generating icon or captcha
        self._watcher = None
        self._watcher_loop_task = None
        try:
            from app.services.watcher import WatcherService, WatcherConfig
            cfg = WatcherConfig(
                enabled=bool(self.config.get_state("watcher_enabled", False)),
                check_interval_ms=int(self.config.get_state("watcher_interval_ms", 2000)),
                captcha_timeout_sec=int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
                generation_timeout_sec=int(self.config.get_state("watcher_generation_timeout_sec", 600)),
                auto_pause_jobs=bool(self.config.get_state("watcher_auto_pause", True)),
            )
            self._watcher = WatcherService(
                config=cfg,
                cdp_controller_getter=lambda: get_watcher_cdp_controller(self),
                job_runner_getter=lambda: self,
                logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
            )
            # Callback to emit watcher_status to UI
            def _watcher_cb(payload):
                try:
                    import json as _json
                    self.watcher_status.emit(_json.dumps(payload, ensure_ascii=False))
                except Exception:
                    pass
            # Use sync callback that will be called from async loop — need to handle via signal
            # We'll wrap to emit via log as well
            self._watcher.add_callback(lambda p: on_watcher_state(self, p))
            # Auto-start if enabled
            if cfg.enabled:
                # Start will be called when event loop is ready — schedule
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        self._watcher.start()
                    else:
                        # Will start on first get_watcher_config call or explicit start
                        pass
                except Exception:
                    pass
        except Exception as e:
            try:
                self._log(f"Watcher init failed: {e}", "warn")
            except Exception:
                pass
            self._watcher = None

        # PagePool — multi-page steady/busy tracking
        self._page_pool = None
        try:
            from app.browser.page_pool import PagePool
            self._page_pool = PagePool(logger=lambda m, l="info": self._log(m, l))
            try:
                host = self.config.get_state("cdp_host", "127.0.0.1")
                port = int(self.config.get_state("cdp_port", 9222))
            except Exception:
                host = "127.0.0.1"
                port = 9222
            self._page_pool._host = str(host)
            self._page_pool._port = int(port)
        except Exception as e:
            try:
                self._log(f"PagePool init failed: {e}", "warn")
            except Exception:
                pass
            self._page_pool = None
        self._log_build_version()

    def _log_build_version(self) -> None:
        """Log the running commit so behavior is traceable. Best effort."""
        try:
            import subprocess
            here = Path(__file__).resolve().parents[2]
            sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=here, timeout=5).stdout.strip()
            if sha:
                self._log(f"📌 Build {sha}", "info")
        except Exception:
            pass

    def _emit_pool_status(self):
        try:
            if not self._page_pool:
                return
            snap = self._page_pool.status_snapshot()
            self.page_pool_updated.emit(json.dumps(snap, ensure_ascii=False))
            self._persist_cooldowns()
        except Exception:
            pass


    def _persist_cooldowns(self):
        # Contract §2: run_state owns cooldown persistence.
        return persist_cooldowns(self)

    def _on_cdp_error(self, err_msg: str):
        try:
            self._log(f"CDP error: {err_msg[:500]}", "error")
        except Exception:
            pass
        try:
            self.connection_status.emit("error")
        except Exception:
            pass

    # ---- Action Blocks — stacking jobs with visual confirmations ----
    def _get_action_blocks(self):
        return blocks_stack.get_action_blocks(self)

    def _emit_action_blocks(self):
        blocks_stack.emit_action_blocks(self)

    def _emit_job_action_status(self, job_id: str, block: Any, status: str, message: str = "", rect: dict = None):
        try:
            # block can be ActionBlock or dict or block_id string
            if isinstance(block, str):
                block_id = block
                block_name = block
                color = "#FF0000"
                highlight_ms = 2000
            else:
                block_id = getattr(block, 'id', '') or getattr(block, 'block_id', '') or str(block)
                block_name = getattr(block, 'display_name', None) or getattr(block, 'name', block_id)
                if callable(block_name):
                    block_name = block_name()
                color = getattr(block, 'color', '#FF0000')
                highlight_ms = getattr(block, 'highlight_duration_ms', 2000)
            payload = json.dumps({
                "job_id": job_id,
                "block_id": block_id,
                "block_name": block_name,
                "status": status,  # pending, running, success, failed, skipped
                "message": message,
                "rect": rect,
                "color": color,
                "highlight_duration_ms": highlight_ms,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }, ensure_ascii=False)
            self.job_action_status.emit(job_id, block_id, payload)
            # Also emit highlight rect if rect provided
            if rect and status in ("running", "success"):
                try:
                    hr = {
                        "x": rect.get("x", 0),
                        "y": rect.get("y", 0),
                        "width": rect.get("width", 100),
                        "height": rect.get("height", 100),
                        "duration": highlight_ms / 1000 if highlight_ms else 2,
                        "label": block_name,
                        "color": color,
                    }
                    self.highlight_rect.emit(json.dumps(hr))
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"emit job action status failed: {e}")


    def _save_arena(self):
        layout_state.save_arena_state(self)

    def _emit_arena_state(self):
        layout_state.emit_arena_state(self)

    def _log(self, msg: str, level: str = "info"):
        # Emit only arena_log to avoid duplicate logs (previously emitted both log_message and arena_log
        # which JS connected both to LogConsole.log causing double lines)
        try:
            self.arena_log.emit(msg, level)
        except Exception:
            pass
        try:
            # Also try log_message but JS now dedupes? Keep only arena_log for single log
            # self.log_message.emit(msg, level)
            pass
        except Exception:
            pass



    def _push_queue_undo(self):
        # R3 shim: queue_scan owns push_queue_undo; R9 deletes this with the last callers.
        return push_queue_undo(self)

    @Slot(result=str)
    def retry_failed(self):
        count = 0
        for img in self.state.images:
            if img.status == "failed":
                img.status = "pending"
                img.selected = True
                img.error = None
                count += 1
        self.state.recalculate_progress()
        self._save_arena()
        self._push_queue_undo()
        return json.dumps({"ok": True, "count": count})

    @Slot(result=str)
    def clear_queue(self):
        """Clear entire image queue — start new batch. User requested: should able to start new batch not adding only."""
        try:
            count = len(self.state.images)
            # push undo before clearing so user can undo
            try:
                self._push_queue_undo()
            except Exception:
                pass
            self.state.images = []
            self.state.jobs = []
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"🗑 Cleared image queue: {count} images removed — ready for new batch", "warn")
            return json.dumps({"ok": True, "count": count})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def reset_all(self):
        for img in self.state.images:
            img.status = "pending"
            img.selected = False
            img.error = None
            img.output_path = None
            img.assigned_url_id = None
            img.attempt_count = 0
        self.state.jobs = []
        self.state.recalculate_progress()
        self._save_arena()
        self._push_queue_undo()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def retry_image(self, img_id: str):
        for img in self.state.images:
            if img.id == img_id:
                img.status = "pending"
                img.selected = True
                img.error = None
                self.state.recalculate_progress()
                self._save_arena()
                self._push_queue_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def reset_image(self, img_id: str):
        for img in self.state.images:
            if img.id == img_id:
                img.status = "pending"
                img.selected = False
                img.error = None
                img.output_path = None
                img.assigned_url_id = None
                img.attempt_count = 0
                self.state.recalculate_progress()
                self._save_arena()
                self._push_queue_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    # ---- run controls — real implementation via CDP ----
    def _get_selected_images(self):
        return selected_images(self.state.images)

    def _get_enabled_urls(self):
        return [u for u in self.state.urls if u.enabled]

    @Slot(result=str)
    def start_run(self):
        prompt = self.state.prompt.get("user_prompt","").strip()
        if not prompt:
            self._log("⚠ Prompt is empty — set prompt before running", "warn")
            return json.dumps({"ok": False, "error": "empty prompt"})
        selected = self._get_selected_images()
        if not selected:
            self._log("⚠ No selected images — select images in queue", "warn")
            return json.dumps({"ok": False, "error": "no selected images"})
        urls = self._get_enabled_urls()
        gate = _urls_gate_error(self, urls)
        if gate:
            msg, level = _URL_GATE_MSG[gate]
            self._log(msg, level)
            return json.dumps({"ok": False, "error": gate})
        if not self.cdp or not self.cdp.is_connected:
            self._log("❌ Chrome not connected — click Diagnose, Refresh, Connect first. CDP must be connected to automate.", "error")
            return json.dumps({"ok": False, "error": "cdp not connected"})
        if self._run_state == "running":
            self._log("⚠ Already running", "warn")
            return json.dumps({"ok": False, "error": "already running"})
        self._run_state = "running"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._log(f"🚀 Run started: {len(selected)} images, {len(urls)} urls, prompt len {len(prompt)}", "success")
        self._emit_arena_state()
        from app.services.batch_orchestrator import run_batch
        fut = self._schedule_coro(run_batch(self))
        if fut:
            self._batch_future = fut
        return json.dumps({"ok": True})

    @Slot(result=str)
    def pause_run(self):
        self._pause_requested = True
        self._run_state = "paused"
        self._log("⏸ Paused — will pause after current step", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def resume_run(self):
        self._pause_requested = False
        self._run_state = "running"
        self._log("▶ Resumed", "info")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def stop_after_current(self):
        self._stop_after = True
        self._run_state = "stopping"
        self._log("⏹ Will stop after current image", "warn")
        self._emit_arena_state()
        return json.dumps({"ok": True})

    @Slot(result=str)
    def cancel_current(self):
        self._cancel_requested = True
        self._run_state = "idle"
        self._pause_requested = False
        self._stop_after = False
        self._log("✖ Cancel requested — stopping immediately", "error")
        self._emit_arena_state()
        # Try to cancel running batch future immediately
        try:
            if self._batch_future:
                self._batch_future.cancel()
                self._log("✖ Batch future cancelled", "warn")
        except Exception as e:
            self._log(f"Cancel future failed: {e}", "warn")
        try:
            # Also emit job_finished cancelled for current jobs
            from app.core.enums import ImageStatus
            for img in self._get_selected_images():
                if img.status == ImageStatus.PROCESSING.value:
                    img.status = ImageStatus.FAILED.value
                    img.error = "Cancelled by user"
            self.state.recalculate_progress()
            self._save_arena()
        except Exception:
            pass
        return json.dumps({"ok": True})

    # ---- watcher win — passive recheck every x ms for generating icon or captcha ----
    # ---- PagePool — multi-page steady/busy tracking ----
    # ---- 2Captcha solving (opt-in, RULE 20 as amended 2026-09-17) ----
    # WebChannel constraint: slots must live on this QObject (wire format);
    # the lazy getter keeps __init__ untouched. Net line delta of this
    # change is negative (inline captcha blocks replaced by choke point).

    def _captcha_service(self):
        # Seam for main_window + app/services/captcha (watcher_captcha owns the factory).
        return captcha_service(self)

    @Slot(str, result=str)
    def highlight_image(self, img_id: str):
        self._emit_highlight_demo()
        if self.cdp and self.cdp.is_connected:
            self._schedule_coro(self._do_highlight_demo_cdp(img_id))
        return json.dumps({"ok": True})

    async def _do_highlight_demo_cdp(self, img_id: str):
        try:
            duration = self.config.get_state("highlight_duration", 3)
            duration_ms = int(duration * 1000) if duration else 2000
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            await ctrl.highlight_selector('textarea[name="message"]', color="#FF0000", duration_ms=duration_ms, caption=f"Image {img_id[:8]}" if img_id else "Clicked element")
            self.highlight_rect.emit(json.dumps({"x":200,"y":200,"width":320,"height":180,"duration":duration,"label":f"Image {img_id}" if img_id else "Clicked element"}))
        except Exception as e:
            self._log(f"Highlight failed: {e}", "warn")

    # ---- undo system ----
    def _emit_highlight_demo(self):
        duration = self.config.get_state("highlight_duration", 3)
        rect = {
            "x": 200,
            "y": 200,
            "width": 320,
            "height": 180,
            "duration": duration,
            "label": "Clicked element"
        }
        self.highlight_rect.emit(json.dumps(rect))

    # ---- CDP Chrome connection (robust, non-blocking to avoid UI freeze) ----
    # Persistent background asyncio loop to keep CDP websocket receive_task alive.
    # Previous short-lived asyncio.run() closed loop immediately after connect(),
    # cancelling receive_task and causing instant disconnect.
    def _ensure_bg_loop(self):
        """Ensure a background event loop thread exists and is running."""
        try:
            import asyncio
            import threading
            # Ensure lock/event exist (robust against old None values from previous version)
            if not isinstance(getattr(self, '_bg_lock', None), type(threading.Lock())):
                # _bg_lock may be None or wrong type after unpickle/migration — recreate
                self._bg_lock = threading.Lock()
            if not isinstance(getattr(self, '_bg_ready', None), type(threading.Event())):
                self._bg_ready = threading.Event()
            # If loop exists and running, reuse
            bg_loop = getattr(self, '_bg_loop', None)
            if bg_loop and bg_loop.is_running():
                return bg_loop
            with self._bg_lock:
                bg_loop = getattr(self, '_bg_loop', None)
                if bg_loop and bg_loop.is_running():
                    return bg_loop
                try:
                    self._bg_ready.clear()
                except Exception:
                    self._bg_ready = threading.Event()
                def _run_loop():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        self._bg_loop = loop
                        try:
                            self._bg_ready.set()
                        except Exception:
                            pass
                        loop.run_forever()
                    except Exception as e:
                        log.warning(f"bg loop crashed: {e}")
                        try:
                            self._bg_ready.set()
                        except Exception:
                            pass
                t = threading.Thread(target=_run_loop, daemon=True, name="arena-bg-loop")
                t.start()
                self._bg_thread = t
            # Wait for loop to be ready
            try:
                self._bg_ready.wait(timeout=5)
            except Exception:
                pass
            return getattr(self, '_bg_loop', None)
        except Exception as e:
            import traceback
            log.warning(f"_ensure_bg_loop failed: {e} {traceback.format_exc()[-500:]}")
            return None

    def _schedule_coro(self, coro):
        """Schedule coro on persistent background loop via run_coroutine_threadsafe.
        This keeps CDP websocket receive loop alive after connect, unlike short-lived asyncio.run.
        Non-blocking for UI thread.
        """
        try:
            import asyncio
            loop = self._ensure_bg_loop()
            if loop and loop.is_running():
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                # Store batch future for immediate cancel
                try:
                    # Heuristic: if coro is the batch runner, keep reference
                    if hasattr(coro, 'cr_code') and coro.cr_code.co_name == 'run_batch':
                        self._batch_future = future
                except Exception:
                    pass
                def _cb(fut):
                    try:
                        fut.result()
                    except Exception as e:
                        # Ignore CancelledError after cancel
                        try:
                            import concurrent.futures
                            if isinstance(e, concurrent.futures.CancelledError):
                                return
                        except Exception:
                            pass
                        log.warning(f"coro thread failed: {e}")
                        try:
                            self._log(f"Async task failed: {e}", "error")
                        except Exception:
                            pass
                    finally:
                        # Clear batch future when done
                        try:
                            if self._batch_future is fut:
                                self._batch_future = None
                        except Exception:
                            pass
                future.add_done_callback(_cb)
                return future
            # Fallback: short-lived thread if bg loop not available
            import threading
            def _run():
                try:
                    asyncio.run(coro)
                except Exception as e:
                    log.warning(f"coro thread fallback failed: {e}")
                    try:
                        self._log(f"Async task failed: {e}", "error")
                    except Exception:
                        pass
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            return None
        except Exception as e:
            log.warning(f"_schedule_coro failed: {e}")
            try:
                coro.close()
            except Exception:
                pass


    # URL bookmarks (from old app, now using arena_presets)
    # Arena presets (full)
    # Prompt presets
    # Highlight via CDP
    @Slot(str, str, int, str, result=str)
    def highlight_selector(self, selector: str, color: str, duration_ms: int, caption: str):
        if not self.cdp or not self.cdp.is_connected:
            # fallback to UI overlay
            rect = {
                "x": 200, "y": 200, "width": 320, "height": 180,
                "duration": duration_ms / 1000 if duration_ms>0 else 2,
                "label": caption or selector,
                "color": color
            }
            self.highlight_rect.emit(json.dumps(rect))
            return json.dumps({"ok": True, "fallback": True})
        # schedule async highlight
        self._schedule_coro(self._do_highlight(selector, color, duration_ms, caption))
        return json.dumps({"ok": True})

    async def _do_highlight(self, selector: str, color: str, duration_ms: int, caption: str):
        try:
            js = build_highlight_js(selector, color or "#FF0000", duration_ms or 2000, caption or selector, clear_first=True)
            result_json = await self.cdp.evaluate(js)
            if result_json:
                try:
                    data = json.loads(result_json) if isinstance(result_json, str) else result_json
                    if data.get("found") and data.get("rect"):
                        r = data["rect"]
                        rect = {
                            "x": r.get("x",0), "y": r.get("y",0),
                            "width": r.get("width",100), "height": r.get("height",100),
                            "duration": (duration_ms or 2000)/1000,
                            "label": caption or selector,
                            "color": color
                        }
                        self.highlight_rect.emit(json.dumps(rect))
                        self._log(f"🔍 Highlighted {selector} at {r}", "success")
                    else:
                        self._log(f"⚠ Highlight not found: {selector}", "warn")
                except Exception as e:
                    self._log(f"Highlight parse failed: {e}", "warn")
        except Exception as e:
            self._log(f"Highlight failed: {e}", "error")

    @Slot(result=str)
    def clear_highlights(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": True})
        self._schedule_coro(self._do_clear_highlights())
        return json.dumps({"ok": True})

    async def _do_clear_highlights(self):
        try:
            js = build_clear_js()
            await self.cdp.evaluate(js)
            self._log("Highlights cleared", "info")
        except Exception as e:
            self._log(f"Clear highlights failed: {e}", "error")

    # ---- CDP config user decides port and user-data-dir ----
    @Slot(result=str)
    def get_cdp_config(self):
        try:
            host = self.config.get_state("cdp_host", "127.0.0.1")
            port = self.config.get_state("cdp_port", 9222)
            user_data_dir = self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome")
            extra = self.config.get_state("cdp_extra_args", "")
            url_pattern = self.config.get_state("url_pattern", "arena.ai")
            payload = {
                "host": host,
                "port": int(port),
                "user_data_dir": user_data_dir,
                "extra_args": extra,
                "url_pattern": url_pattern,
                "base_url": f"http://{host}:{port}",
                "is_connected": bool(self.cdp and self.cdp.is_connected),
                "current_host": self.cdp._host if self.cdp else host,
                "current_port": self.cdp._port if self.cdp else int(port),
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def set_cdp_config(self, config_json: str):
        try:
            data = json.loads(config_json or "{}")
            host = data.get("host") or data.get("cdp_host") or "127.0.0.1"
            port = data.get("port") or data.get("cdp_port") or 9222
            user_data_dir = data.get("user_data_dir") or data.get("cdp_user_data_dir") or "C:\\arena-images-chrome"
            extra = data.get("extra_args") or data.get("cdp_extra_args") or ""
            url_pattern = data.get("url_pattern", self.config.get_state("url_pattern", "arena.ai"))
            url_pattern = url_pattern.strip() if isinstance(url_pattern, str) else "arena.ai"
            # validate
            try:
                port_i = int(port)
                if not (1 <= port_i <= 65535):
                    return json.dumps({"ok": False, "error": "port must be 1-65535"})
            except:
                return json.dumps({"ok": False, "error": "invalid port"})
            # save to session
            self.config.set_state(cdp_host=host, cdp_port=port_i, cdp_user_data_dir=user_data_dir, cdp_extra_args=extra,
                                  url_pattern=url_pattern)
            # update cdp client
            if self.cdp:
                try:
                    self.cdp.set_host_port(host, port_i)
                except Exception:
                    pass
            if self._page_pool:
                try:
                    self._page_pool._host = str(host)
                    self._page_pool._port = int(port_i)
                except Exception:
                    pass
            self._log(f"CDP config saved: {host}:{port_i} dir={user_data_dir}", "success")
            return json.dumps({"ok": True, "host": host, "port": port_i, "user_data_dir": user_data_dir})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_chrome_launch_command(self):
        try:
            host = self.config.get_state("cdp_host", "127.0.0.1")
            port = self.config.get_state("cdp_port", 9222)
            user_data_dir = self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome")
            extra = self.config.get_state("cdp_extra_args", "")
            # Windows command
            win_cmd = f'"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
            if extra:
                win_cmd += f" {extra}"
            # Also with URL placeholder
            win_cmd_with_url = win_cmd + " https://arena.ai"
            # Linux/Mac
            linux_cmd = f'google-chrome --remote-debugging-port={port} --user-data-dir="{user_data_dir}"'
            if extra:
                linux_cmd += f" {extra}"
            payload = {
                "host": host,
                "port": int(port),
                "user_data_dir": user_data_dir,
                "extra_args": extra,
                "windows": win_cmd,
                "windows_with_url": win_cmd_with_url,
                "linux": linux_cmd,
                "test_url": f"http://{host}:{port}/json/list",
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def cdp_attach_image_test(self, image_id: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        # Find image
        img = None
        for im in self.state.images:
            if im.id == image_id or (not image_id and im.selected):
                img = im
                break
        if not img:
            # fallback first selected
            sel = [i for i in self.state.images if i.selected]
            if sel:
                img = sel[0]
        if not img:
            return json.dumps({"ok": False, "error": "No image found, select one in queue"})
        self._log(f"🧪 Testing attach for {img.absolute_path}", "info")
        self._schedule_coro(self._do_cdp_attach_test(img.absolute_path))
        return json.dumps({"ok": True, "path": img.absolute_path})

    async def _do_cdp_attach_test(self, image_path: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ok, reason = await ctrl.attach_image(image_path)
            if ok:
                self._log(f"✅ Attach test success: {reason}", "success")
            else:
                self._log(f"❌ Attach test failed: {reason}", "error")
        except Exception as e:
            self._log(f"Attach test exception: {e}", "error")

    @Slot(str, result=str)
    def cdp_insert_prompt_test(self, prompt_text: str):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        txt = prompt_text or self.state.prompt.get("user_prompt","") or "Test prompt [JOB-ID: test123]"
        self._log(f"🧪 Testing prompt insert: {txt[:80]}...", "info")
        self._schedule_coro(self._do_cdp_prompt_test(txt))
        return json.dumps({"ok": True})

    async def _do_cdp_prompt_test(self, prompt_text: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            ok, reason = await ctrl.insert_prompt(prompt_text)
            if ok:
                self._log(f"✅ Prompt insert success: {reason}", "success")
                verified, vreason = await ctrl.verify_prompt(prompt_text)
                self._log(f"Verify prompt: {verified} {vreason}", "info" if verified else "warn")
            else:
                self._log(f"❌ Prompt insert failed: {reason}", "error")
        except Exception as e:
            self._log(f"Prompt test exception: {e}", "error")

    @Slot(result=str)
    def cdp_test_full_flow(self):
        if not self.cdp or not self.cdp.is_connected:
            return json.dumps({"ok": False, "error": "CDP not connected"})
        sel = [i for i in self.state.images if i.selected]
        if not sel:
            return json.dumps({"ok": False, "error": "No selected image"})
        prompt = self.state.prompt.get("user_prompt","")
        if not prompt:
            return json.dumps({"ok": False, "error": "Empty prompt"})
        self._log(f"🧪 Testing full flow: attach + prompt + submit (without waiting)", "info")
        self._schedule_coro(self._do_cdp_full_flow_test(sel[0].absolute_path, prompt))
        return json.dumps({"ok": True})

    async def _do_cdp_full_flow_test(self, image_path: str, prompt_template: str):
        try:
            from app.browser.cdp_arena import CDPArenaController
            from app.utils.correlation import generate_correlation_id, build_final_prompt
            ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
            baseline = await ctrl.capture_baseline()
            self._log(f"Baseline {baseline.get('output_count')} outputs", "info")
            ok, reason = await ctrl.attach_image(image_path)
            self._log(f"Attach: {ok} {reason}", "success" if ok else "error")
            if not ok:
                return
            cid = generate_correlation_id()
            final = build_final_prompt(cid, prompt_template)
            ok, reason = await ctrl.insert_prompt(final)
            self._log(f"Insert prompt [{cid}]: {ok} {reason}", "success" if ok else "error")
            if not ok:
                return
            ok, reason = await ctrl.submit()
            self._log(f"Submit: {ok} {reason}", "success" if ok else "error")
        except Exception as e:
            self._log(f"Full flow test exception: {e}", "error")


"""Run Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import asyncio
import json
try:
    from PySide6.QtCore import QObject, Signal, Slot
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6) — exercised by tests/test_qt_shim_fallback.py
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

    def Slot(*slot_shim_args, **slot_shim_kwargs):
        def deco(fn): return fn
        return deco

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    QFileDialog = None



from app.ui.panels._bridge_helpers import _URL_GATE_MSG
from app.ui.panels._bridge_helpers import _urls_gate_error

class RunControlPanel:

    def _start_run_preflight(self):
        """None when OK to run, else error json (prompt/images/urls/cdp/state)."""
        prompt = self.state.prompt.get("user_prompt", "").strip()
        if not prompt:
            self._log("⚠ Prompt is empty — set prompt before running", "warn")
            return json.dumps({"ok": False, "error": "empty prompt"})
        if not self._get_selected_images():
            self._log("⚠ No selected images — select images in queue", "warn")
            return json.dumps({"ok": False, "error": "no selected images"})
        gate = _urls_gate_error(self, self._get_enabled_urls())
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
        return None

    @Slot(result=str)
    def start_run(self):
        err = self._start_run_preflight()
        if err:
            return err
        prompt = self.state.prompt.get("user_prompt", "").strip()
        selected = self._get_selected_images()
        urls = self._get_enabled_urls()
        self._run_state = "running"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._log(f"🚀 Run started: {len(selected)} images, {len(urls)} urls, prompt len {len(prompt)}", "success")
        self._emit_arena_state()
        fut = self._schedule_coro(self._do_run_batch())
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

    async def _settle_boundary_captcha(self, ctrl, primary_tab_id, correlation_id, source):
        """F4: captcha at a phase boundary — auto-solve or wait, then record."""
        await self._settle_captcha_at(ctrl, primary_tab_id, correlation_id, source)

    def _settle_stuck_primary(self, primary_tab_id) -> None:
        """Best-effort steady for a busy-like primary page; cooling untouched."""
        try:
            from app.services.cooldown_service import is_stuck_status
            if not (self._page_pool and primary_tab_id):
                return
            page = self._page_pool.get_page(primary_tab_id)
            if page is not None and is_stuck_status(page.status):
                self._page_pool.mark_steady(primary_tab_id)
        except Exception:
            pass

    async def _do_run_batch(self):
        """Run the batch via the extracted orchestrator (W1.5)."""
        from app.services.batch_orchestrator import run_batch
        await run_batch(self)


class RunTabsPanel:

    def _get_selected_images(self):
        return [img for img in self.state.images if img.selected and img.status in ("pending","failed","selected","needs_review","processing")]

    def _get_enabled_urls(self):
        return [u for u in self.state.urls if u.enabled]

    async def _select_run_tab(self, primary_tab_id, allowed=None) -> str:
        """Prefer a ready pooled tab owned by a checked row (I-33)."""
        try:
            from app.services.cooldown_service import resolve_primary_tab
            want = resolve_primary_tab(self._page_pool, primary_tab_id, allowed)
        except Exception:
            return primary_tab_id
        if not want:
            return ""
        if want == primary_tab_id:
            self._log_stay_reason(primary_tab_id)
            return primary_tab_id
        return await self._try_move_to_tab(want, primary_tab_id)

    async def _try_move_to_tab(self, want, primary_tab_id) -> str:
        """Reconnect cdp to the ready tab; fall back to primary on failure."""
        try:
            page = self._page_pool.get_page(want) if self._page_pool else None
            ws = getattr(page, "ws_url", "") or ""
            if ws and self.cdp and await self.cdp.connect(ws):
                self._log(f"🔀 Run moved to ready tab {want[:12]}", "info")
                return want
            self._log(f"⚠ Reconnect to ready tab {want[:12]} failed — staying on {(primary_tab_id or '?')[:12]} — pool: {self._pool_summary()}", "warn")
        except Exception as e:
            self._log(f"⚠ Primary move failed ({e}) — pool: {self._pool_summary()}", "warn")
        return primary_tab_id

    def _log_stay_reason(self, primary_tab_id) -> None:
        """Warn when staying on an unready primary, with pool state."""
        try:
            if not (self._page_pool and primary_tab_id):
                return
            page = self._page_pool.get_page(primary_tab_id)
            if page is None or page.is_free():
                return
            self._log(f"⏳ No ready tab — staying on {primary_tab_id[:12]} ({page.status}) — pool: {self._pool_summary()}", "warn")
        except Exception:
            pass

    def _pool_summary(self) -> str:
        """One-line pool state for run decisions."""
        try:
            pages = self._page_pool.status_snapshot().get("pages", [])
        except Exception:
            return "pool n/a"
        bits = []
        for p in pages:
            bit = f"{(p.get('tab_id') or '?')[:6]}:{p.get('status')}({'c' if p.get('is_connected') else 'd'})"
            bit += f"·j{p.get('jobs_completed', 0)}"
            if p.get("current_image"):
                bit += f"·▶{p.get('current_image')}"
            bits.append(bit)
        return ", ".join(bits) or "pool empty"

    def _run_stop_requested(self, tab_id) -> bool:
        """Global cancel or operator stop for this tab."""
        if self._cancel_requested:
            return True
        try:
            from app.services.cooldown_service import is_tab_aborted
            return is_tab_aborted(self._page_pool, tab_id)
        except Exception:
            return False

    def _stop_reason(self, tab_id) -> str:
        """User-facing stop reason for this tab."""
        try:
            from app.services.cooldown_service import is_tab_aborted
            if is_tab_aborted(self._page_pool, tab_id):
                return "Aborted by operator"
        except Exception:
            pass
        return "Cancelled by user"

    def _start_tab_image(self, tab_id, img) -> None:
        """Record the image on its tab; drop any stale stop request."""
        try:
            import os
            from app.services.cooldown_service import clear_tab_abort, set_tab_image
            clear_tab_abort(self._page_pool, tab_id)
            set_tab_image(self._page_pool, tab_id, os.path.basename(img.relative_path or ""))
            self._emit_pool_status()
        except Exception:
            pass

    async def _finish_primary_tab(self, ctrl, primary_tab_id) -> None:
        """Post-job reset + cooldown; settles a stuck page when finish fails."""
        try:
            from app.services.cooldown_service import FinishCtx, finish_page_after_job, set_tab_image
            if not (self._page_pool and primary_tab_id):
                return
            ctx = FinishCtx(pool=self._page_pool, bridge=self, tab_id=primary_tab_id,
                            ctrl=ctrl, client=self.cdp)
            await finish_page_after_job(ctx)
            set_tab_image(self._page_pool, primary_tab_id, None)
            self._emit_pool_status()
        except asyncio.CancelledError:
            self._settle_stuck_primary(primary_tab_id)
            raise
        except Exception as e:
            self._log(f"Post-job reset/cooldown skipped: {e} — settling stuck page", "warn")
            self._settle_stuck_primary(primary_tab_id)



class TabInfoPanel:
    """Live tab (title,url) resolution + primary pool registration (W1.6 split)."""

    async def _resolve_tab_info(self, tab_id: str, ws_url: str):
        """Best-known (title, url): live Chrome tabs first, cdp attrs then."""
        title = getattr(self.cdp, "_current_title", "") or ""
        url = getattr(self.cdp, "_current_url", "") or ""
        try:
            tabs = await self.cdp.fetch_tabs()
        except Exception:
            return title, url
        live = self._find_live_tab(tabs, tab_id, ws_url)
        if live is None:
            return title, url
        return getattr(live, "title", "") or title, getattr(live, "url", "") or url

    @staticmethod
    def _find_live_tab(tabs, tab_id, ws_url):
        """Live tab matching tab_id or ws_url, else None."""
        try:
            for t in tabs or []:
                tid = getattr(t, "id", "") or ""
                tws = getattr(t, "ws_url", "") or ""
                if (tab_id and tid == tab_id) or (ws_url and tws == ws_url):
                    return t
        except Exception:
            pass
        return None

    async def _ensure_pool_page(self, tab_id: str):
        """Register primary tab for cooldown tracking (batch self-sufficiency)."""
        try:
            if not self._page_pool or not tab_id:
                return
            page = self._page_pool.get_page(tab_id)
            if page is not None and getattr(page, "url", "") and getattr(page, "title", ""):
                return
            await self._pool_register_primary(tab_id)
        except Exception as e:
            self._log(f"Pool ensure skipped: {e}", "warn")

    async def _pool_register_primary(self, tab_id: str):
        """Register/refresh the primary tab's PageInfo in the pool."""
        ws = getattr(self.cdp, "_current_ws_url", "") or ""
        title = getattr(self.cdp, "_current_title", "") or ""
        url = getattr(self.cdp, "_current_url", "") or ""
        if not url or not title:
            live_title, live_url = await self._resolve_tab_info(tab_id, ws)
            title = title or live_title or tab_id
            url = url or live_url
        from app.browser.page_status import PageInfo
        from app.services.cooldown_service import ensure_pool_page
        ensure_pool_page(self._page_pool, PageInfo(tab_id=tab_id, ws_url=ws, title=title, url=url))
        self._restore_page_state(tab_id)
        self._emit_pool_status()

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

try:
    from PySide6.QtCore import QObject, Signal, Slot
    from PySide6.QtWidgets import QFileDialog
except ImportError:
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
    QFileDialog = None

from app.core.layout_service import (
    GRID_VERSION,
    WINDOW_IDS,
    canonical_grid_payload, default_payload, leaf_ids,
)
from app.core.models import AppState, UrlRow, ImageItem
from app.core.persistence import load_state, save_state, save_preset, load_preset
from app.core.scanner import scan_folder
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService
from app.browser.tab_matcher import best_matches
from app.browser.dom_highlight import build_highlight_js, build_clear_js, build_highlight_probe, build_find_probe, build_click_probe
from app.browser.probe_selectors import send_click_primary, send_presence_selector, textarea_primary
from app.browser.probe_requests import FindProbeSpec, ClickProbeSpec, HighlightSpec, COLOR_FIND, COLOR_CLICK, COLOR_COLLECT
from app.browser.visual_click import ClickRequest, find_and_click
from app.core.action_blocks import (
    default_stack,
    stack_to_dicts,
    load_stack_from_dicts,
    parse_stack_json,
    validate_stack,
    create_default_block,
    BUILTIN_BLOCKS,
    get_builtin_blocks_json,
    BLOCK_DEFINITIONS,
)

log = logging.getLogger("arena")


# ── URL-row ownership helpers (I-33) — module level, keep Bridge slim ──

def _checked_tabs_ready(bridge) -> set:
    """Rescue-claim checked unlinked rows; tab ids usable for runs."""
    from app.services.auto_connect import claim_unlinked_from_pool, enabled_tab_ids
    try:
        pool = bridge._page_pool
        pages = pool.status_snapshot().get("pages", []) if pool else []
        if claim_unlinked_from_pool(bridge.state.urls, pages):
            bridge._save_arena()
    except Exception:
        pass
    return enabled_tab_ids(bridge._get_enabled_urls())


_URL_GATE_MSG = {
    "no enabled urls": ("⚠ No enabled URLs — check a URL row to use it for jobs", "warn"),
    "no checked url linked to a tab": (
        "❌ No checked URL is linked to a live tab — press Reparse or Connect on a checked row first",
        "error"),
}


def _urls_gate_error(bridge, urls) -> str:
    """Start gate: checked URLs must exist and own live tabs (I-33)."""
    if not urls:
        return "no enabled urls"
    if not _checked_tabs_ready(bridge):
        return "no checked url linked to a tab"
    return ""


def _dedupe_state_rows(state_urls) -> tuple[list, int]:
    """Repair legacy N-rows-per-tab state; returns (plan rows, removed)."""
    from app.services.auto_connect import dedupe_linked_rows
    rows = [{"id": u.id, "url": u.url, "tab_id": u.tab_id, "enabled": u.enabled}
            for u in state_urls]
    kept, dropped = dedupe_linked_rows(rows)
    if not dropped:
        return rows, 0
    drop = {r["id"] for r in dropped}
    state_urls[:] = [u for u in state_urls if u.id not in drop]
    return kept, len(dropped)


def _tab_already_owned(urls, tab_id: str) -> bool:
    """One row per tab (I-33): never add a second."""
    for u in urls:
        if u.tab_id == tab_id:
            return True
    return False


def _add_missing_rows(urls, adds) -> int:
    """Append rows for tabs none owns yet; returns count added."""
    added = 0
    for url, tab_id in adds:
        if _tab_already_owned(urls, tab_id):
            continue
        from app.core.models import UrlRow
        urls.append(UrlRow.create(url, enabled=True, tab_id=tab_id))
        added += 1
    return added


class Bridge(QObject):
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
        self._init_state_flags()
        self.undo_service = UndoService(self.config.undo)
        self.cdp = cdp_client
        self._init_thumbnail_infra()
        try:
            self.config.undo.load()
        except Exception:
            pass
        self._wire_cdp_client()
        self._watcher = self._build_watcher_service()
        self._watcher_loop_task = None
        self._page_pool = self._build_page_pool()
        self._log_build_version()

    def _init_state_flags(self) -> None:
        """Construction defaults: run lifecycle, CDP bg loop, debounce guards."""
        self._run_state = "idle"
        self._cancel_requested = self._pause_requested = False
        self._stop_after = False
        self._exported_paths = {}
        self._persist_ok = True
        self._restore_note_done = False
        import threading as _th  # bg CDP loop keeps websocket alive
        self._bg_loop = self._bg_thread = None
        self._bg_lock = _th.Lock()
        self._bg_ready = _th.Event()
        # find/connect debounce avoids x2 logs and races
        self._last_find_query = self._last_connect_ws = ""
        self._last_find_ts = self._last_connect_ts = 0.0
        self._find_in_progress = self._connect_in_progress = False
        self._auto_scan_running = self._ensure_running = False
        self._scan_in_progress = False

    def _init_thumbnail_infra(self) -> None:
        """Thumb cache + pool — PIL thumbnails off the main thread (80-img freeze)."""
        self._thumb_cache = {}
        self._thumb_in_progress = set()
        try:
            import concurrent.futures as _cf
            self._thumb_executor = _cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
        except Exception:
            self._thumb_executor = None

    def _wire_cdp_client(self) -> None:
        """Install CDP status forwarding signals if a client exists."""
        if not self.cdp:
            return
        try:
            self.cdp.connected.connect(lambda: self.connection_status.emit("connected"))
            self.cdp.disconnected.connect(lambda: self.connection_status.emit("disconnected"))
            self.cdp.error.connect(lambda e: self._on_cdp_error(e))
        except Exception:
            pass

    def _build_watcher_service(self):
        """Watcher service — passive recheck every x ms for generating icon
        or captcha. Returns the service, or None on init failure."""
        try:
            from app.services.watcher import WatcherService
            cfg = self._build_watcher_config()
            self._watcher = WatcherService(
                config=cfg,
                cdp_controller_getter=lambda: self._get_watcher_cdp_controller(),
                job_runner_getter=lambda: self,
                logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
            )
            self._watcher.add_callback(lambda p: self._on_watcher_state(p))
            if cfg.enabled:  # auto-start only when a loop is already running
                try:
                    import asyncio
                    if asyncio.get_event_loop().is_running():
                        self._watcher.start()
                except Exception:
                    pass
            return self._watcher
        except Exception as e:
            try:
                self._log(f"Watcher init failed: {e}", "warn")
            except Exception:
                pass
            return None

    def _build_watcher_config(self):
        """Watcher settings from user config (intervals, timeouts, pause)."""
        from app.services.watcher import WatcherConfig

        return WatcherConfig(
            enabled=bool(self.config.get_state("watcher_enabled", False)),
            check_interval_ms=int(self.config.get_state("watcher_interval_ms", 2000)),
            captcha_timeout_sec=int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
            generation_timeout_sec=int(self.config.get_state("watcher_generation_timeout_sec", 600)),
            auto_pause_jobs=bool(self.config.get_state("watcher_auto_pause", True)),
        )

    def _build_page_pool(self):
        """PagePool — multi-page steady/busy tracking bound to CDP host/port."""
        try:
            from app.browser.page_pool import PagePool
            pool = PagePool(logger=lambda m, l="info": self._log(m, l))
            try:
                host = self.config.get_state("cdp_host", "127.0.0.1")
                port = int(self.config.get_state("cdp_port", 9222))
            except Exception:
                host, port = "127.0.0.1", 9222
            pool._host = str(host)
            pool._port = int(port)
            return pool
        except Exception as e:
            try:
                self._log(f"PagePool init failed: {e}", "warn")
            except Exception:
                pass
            return None

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

    async def _resolve_tab_info(self, tab_id: str, ws_url: str):
        """Best-known (title, url): live Chrome tabs first, cdp attrs then."""
        title = getattr(self.cdp, "_current_title", "") or ""
        url = getattr(self.cdp, "_current_url", "") or ""
        try:
            tabs = await self.cdp.fetch_tabs()
        except Exception:
            return title, url
        try:
            for t in tabs or []:
                tid = getattr(t, "id", "") or ""
                tws = getattr(t, "ws_url", "") or ""
                if (tab_id and tid == tab_id) or (ws_url and tws == ws_url):
                    return getattr(t, "title", "") or title, getattr(t, "url", "") or url
        except Exception:
            pass
        return title, url

    async def _ensure_pool_page(self, tab_id: str):
        """Register primary tab for cooldown tracking (batch self-sufficiency)."""
        try:
            if not self._page_pool or not tab_id:
                return
            page = self._page_pool.get_page(tab_id)
            if page is not None and getattr(page, "url", "") and getattr(page, "title", ""):
                return
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
        except Exception as e:
            self._log(f"Pool ensure skipped: {e}", "warn")

    def _cooldowns_path(self):
        """config/cooldowns.json next to the other stores."""
        try:
            base = getattr(self.config, "dir", None)
            if base:
                return str(Path(base) / "cooldowns.json")
        except Exception:
            pass
        return "config/cooldowns.json"

    def _persist_cooldowns(self):
        """Autosave wall-clock timers + job counters across restarts."""
        try:
            if not self._page_pool:
                return
            from app.persistence.cooldown_store import save_pool_snapshot
            save_pool_snapshot(self._cooldowns_path(), self._page_pool)
            if not self._persist_ok:
                self._persist_ok = True
                self._log("✅ Cooldown autosave recovered", "success")
        except Exception as e:
            if self._persist_ok:
                self._persist_ok = False
                self._log(f"⚠ Cooldown autosave failing ({e}) — timers will NOT survive restart", "warn")

    def _restore_job_counter(self, tab_id: str, page_url: str):
        """Re-apply one tab's saved job counter (never moves backwards)."""
        try:
            from app.persistence.cooldown_store import load_stats, normalize_url
            from app.services.cooldown_service import restore_page_stats
            stats = load_stats(self._cooldowns_path())
            restore_page_stats(self._page_pool, tab_id, normalize_url(page_url), stats)
        except Exception:
            pass

    def _log_restore_miss(self, tab_id: str, page_url: str, entries: dict, report: dict):
        """Loud miss: file-level notes once, tab-level mismatch per tab."""
        if report.get("live", 0) == 0:
            if self._restore_note_done:
                return
            self._restore_note_done = True
            if not report.get("exists"):
                self._log("⏳ No saved timers file yet — nothing to resume", "info")
            elif report.get("dropped"):
                self._log(f"⏳ Saved timer(s) already expired while app was closed "
                          f"({len(report['dropped'])} dropped) — tab starts ready", "info")
            else:
                self._log("⏳ Saved timers file is empty — nothing to resume", "info")
            return
        want = f"{tab_id[:12]} / {page_url[:60]}"
        have = ", ".join(f"{k[:8]}:{(v.get('url', '') if isinstance(v, dict) else '')[:40]}"
                         for k, v in list(entries.items())[:5])
        self._log(f"⚠ Cooldown restore missed for {want} — {report['live']} live saved timer(s) "
                  f"for other tabs ({have}); tab ids/URLs changed since save?", "warn")

    def _apply_restored_entry(self, path: str, entries: dict, tab_id: str, entry: dict):
        """Apply a consumed entry: persist it back, announce, emit."""
        from app.persistence.cooldown_store import save_entries
        from app.services.cooldown_service import restore_cooldown_entry
        if not restore_cooldown_entry(self._page_pool, tab_id, entry):
            return
        save_entries(path, entries)
        page = self._page_pool.get_page(tab_id)
        left = page.remaining_seconds() if page else 0
        self._log(f"⏳ Restored cooldown for {tab_id[:12]}: {left // 60:02d}:{left % 60:02d} left (timer kept running while app was closed)", "info")
        self._emit_pool_status()

    def _restore_page_state(self, tab_id: str):
        """Re-apply persisted wall-clock pause + job counter after restart."""
        try:
            if not self._page_pool or not tab_id:
                return
            from app.persistence.cooldown_store import consume_entry_for, describe_cooldown_file, load_entries
            path = self._cooldowns_path()
            entries = load_entries(path)
            page = self._page_pool.get_page(tab_id)
            page_url = getattr(page, "url", "") if page else ""
            _key, entry = consume_entry_for(entries, tab_id, page_url, self._pooled_ids())
            self._restore_job_counter(tab_id, page_url)
            if not entry:
                self._log_restore_miss(tab_id, page_url, entries, describe_cooldown_file(path))
                return
            self._apply_restored_entry(path, entries, tab_id, entry)
        except Exception as e:
            self._log(f"Cooldown restore skipped: {e}", "warn")

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
        """Load action blocks from session or default."""
        try:
            raw = self.config.get_state("action_blocks", None)
            if raw is None:
                stack = default_stack()
                return stack
            if isinstance(raw, list):
                return load_stack_from_dicts(raw)
            if isinstance(raw, str):
                return parse_stack_json(raw)
            return default_stack()
        except Exception as e:
            log.warning(f"Failed to load action blocks: {e}")
            return default_stack()

    def _save_action_blocks(self, stack):
        try:
            dicts = stack_to_dicts(stack)
            self.config.set_state(action_blocks=dicts)
            payload = json.dumps(dicts, ensure_ascii=False)
            self.action_blocks_updated.emit(payload)
            # Also push to undo
            try:
                self.undo_service.push("action_blocks", dicts)
                self._emit_undo_state()
            except Exception:
                pass
            return True
        except Exception as e:
            log.warning(f"Failed to save action blocks: {e}")
            return False

    def _emit_action_blocks(self):
        try:
            stack = self._get_action_blocks()
            payload = json.dumps(stack_to_dicts(stack), ensure_ascii=False)
            self.action_blocks_updated.emit(payload)
        except Exception as e:
            log.warning(f"emit action blocks failed: {e}")

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

    @Slot(result=str)
    def get_action_blocks(self):
        try:
            stack = self._get_action_blocks()
            payload = json.dumps(stack_to_dicts(stack), ensure_ascii=False)
            self.action_blocks_updated.emit(payload)
            return payload
        except Exception as e:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_action_blocks(self, blocks_json: str):
        try:
            data = json.loads(blocks_json or "[]")
            if not isinstance(data, list):
                return json.dumps({"ok": False, "error": "must be array"})
            stack = load_stack_from_dicts(data)
            ok, err = validate_stack(stack)
            if not ok:
                return json.dumps({"ok": False, "error": err})
            if self._save_action_blocks(stack):
                self._log(f"Action blocks saved: {len(stack)} blocks", "success")
                return json.dumps({"ok": True, "count": len(stack)})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def add_action_block(self, block_type: str):
        try:
            block_type = (block_type or "").strip().upper()
            if not block_type:
                return json.dumps({"ok": False, "error": "empty block type"})
            stack = self._get_action_blocks()
            new_block = create_default_block(block_type)
            stack.append(new_block)
            if self._save_action_blocks(stack):
                self._log(f"Added action block {block_type}", "success")
                return json.dumps({"ok": True, "id": new_block.id})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def reset_action_blocks(self):
        try:
            stack = default_stack()
            if self._save_action_blocks(stack):
                self._log(f"Action blocks reset to default ({len(stack)} blocks)", "info")
                return json.dumps({"ok": True, "count": len(stack)})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_action_block(self, block_id: str):
        try:
            stack = self._get_action_blocks()
            before = len(stack)
            stack = [b for b in stack if b.id != block_id]
            if len(stack) == before:
                stack = [b for b in self._get_action_blocks() if b.block_id != block_id or b.required]
                if len(stack) == before:
                    return json.dumps({"ok": False, "error": "not found"})
            ok, err = validate_stack(stack)
            if not ok:
                return json.dumps({"ok": False, "error": err})
            if self._save_action_blocks(stack):
                self._log(f"Deleted block {block_id}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_builtin_blocks(self):
        try:
            payload = get_builtin_blocks_json()
            return payload
        except Exception as e:
            return json.dumps([], ensure_ascii=False)

    @Slot(result=str)
    def get_custom_blocks(self):
        try:
            raw = self.config.get_state("custom_blocks", [])
            if isinstance(raw, list):
                return json.dumps(raw, ensure_ascii=False)
            return json.dumps([], ensure_ascii=False)
        except Exception:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_custom_block(self, block_json: str):
        try:
            data = json.loads(block_json or "{}")
            if not isinstance(data, dict) or "block" not in data:
                return json.dumps({"ok": False, "error": "invalid custom block format, need {name, block}"})
            name = data.get("name") or data.get("block", {}).get("custom_name") or data.get("block", {}).get("name") or "Custom"
            entry = {
                "name": name,
                "block": data.get("block"),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                raw = []
            raw = [c for c in raw if c.get("name") != name]
            raw.append(entry)
            self.config.set_state(custom_blocks=raw)
            self._log(f"Custom block saved: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_custom_block(self, name: str):
        try:
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                raw = []
            before = len(raw)
            raw = [c for c in raw if c.get("name") != name]
            if len(raw) == before:
                return json.dumps({"ok": False, "error": "not found"})
            self.config.set_state(custom_blocks=raw)
            self._log(f"Custom block deleted: {name}", "info")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_stack_presets(self):
        try:
            raw = self.config.get_state("stack_presets", [])
            if isinstance(raw, list):
                return json.dumps(raw, ensure_ascii=False)
            return json.dumps([], ensure_ascii=False)
        except Exception:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_stack_preset(self, preset_json: str):
        try:
            from app.core.action_blocks import upsert_stack_preset
            data = json.loads(preset_json or "{}")
            if not isinstance(data, dict):
                return json.dumps({"ok": False, "error": "invalid stack preset format, need {name, blocks}"})
            raw = self.config.get_state("stack_presets", [])
            saved = upsert_stack_preset(raw, data.get("name", ""), data.get("blocks", []))
            self.config.set_state(stack_presets=saved)
            name = (data.get("name") or "").strip()
            self._log(f"Stack preset saved: {name} ({len(data.get('blocks') or [])} blocks)", "success")
            return json.dumps({"ok": True, "name": name})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_stack_preset(self, name: str):
        try:
            from app.core.action_blocks import remove_stack_preset
            raw = self.config.get_state("stack_presets", [])
            kept, removed = remove_stack_preset(raw, name)
            if not removed:
                return json.dumps({"ok": False, "error": "not found"})
            self.config.set_state(stack_presets=kept)
            self._log(f"Stack preset deleted: {name}", "info")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def export_action_blocks(self, blocks_json: str):
        try:
            blocks = json.loads(blocks_json or "[]")
            if not isinstance(blocks, list) or not blocks:
                return json.dumps({"ok": False, "error": "empty stack"})
            payload = json.dumps(blocks, ensure_ascii=False, indent=2)
            fname = f"arena-action-blocks-{datetime.now().strftime('%Y-%m-%d')}.json"
            if QFileDialog is None:
                path = Path("config") / fname
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding="utf-8")
            else:
                folder = QFileDialog.getExistingDirectory(None, "Select folder to export action blocks")
                if not folder:
                    return json.dumps({"ok": False, "cancelled": True})
                path = Path(folder) / fname
                path.write_text(payload, encoding="utf-8")
            self._log(f"Action blocks exported to {path}", "success")
            return json.dumps({"ok": True, "path": str(path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def export_custom_block(self, name: str):
        try:
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                return json.dumps({"ok": False, "error": "no custom blocks"})
            for c in raw:
                if c.get("name") == name:
                    payload = json.dumps(c, ensure_ascii=False, indent=2)
                    path = Path("config") / f"custom_block_{name}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(payload, encoding="utf-8")
                    self._log(f"Custom block exported to {path}", "success")
                    return json.dumps({"ok": True, "path": str(path)})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})


    def _save_arena(self):
        try:
            save_state(self.state, self.state_path)
            self._emit_arena_state()
        except Exception as e:
            log.error(f"Failed to save arena state: {e}")
            self.arena_log.emit(f"Failed to save state: {e}", "error")

    def _arena_to_js(self):
        """Convert AppState to JS-friendly shape matching old bridge expectations."""
        d = self.state.to_dict()
        # urls: map to {id, url, enabled, status, last_error}
        urls_js = []
        for u in d.get("urls", []):
            urls_js.append({
                "id": u.get("id"),
                "url": u.get("url"),
                "enabled": u.get("enabled", True),
                "status": u.get("last_status", "unchecked"),
                "last_error": u.get("error", ""),
                "last_checked": u.get("last_checked"),
                "tab_id": u.get("tab_id", ""),
            })
        # images: map to expected fields
        images_js = []
        for img in d.get("images", []):
            images_js.append({
                "id": img.get("id"),
                "relative_path": img.get("relative_path"),
                "absolute_path": img.get("absolute_path"),
                "filename": img.get("filename"),
                "status": img.get("status", "pending"),
                "selected": img.get("selected", False),
                "assigned_url": img.get("assigned_url_id") or "",
                "attempts": img.get("attempt_count", 0),
                "output_path": img.get("output_path") or "",
                "error": img.get("error") or "",
                "size": img.get("size", 0),
            })
        # prompt: template is user_prompt
        prompt_js = {
            "template": d.get("prompt", {}).get("user_prompt", ""),
        }
        # settings: flatten relevant
        settings_dict = d.get("settings", {})
        timeouts = settings_dict.get("timeouts", {})
        output = settings_dict.get("output", {})
        highlight = settings_dict.get("highlight", {})
        browser = settings_dict.get("browser", {})
        settings_js = {
            "timeout_seconds": timeouts.get("page_load", 30),
            "generation_timeout": timeouts.get("generation", 180),
            "max_retries": settings_dict.get("retries", {}).get("max_attempts", 3),
            "naming_suffix": output.get("suffix", "_AI"),
            "supported_types": d.get("folder", {}).get("supported_types", [".png",".jpg"]),
            "overwrite": output.get("overwrite", False),
            "highlight_duration": highlight.get("duration_seconds", 3),
            "max_concurrent": settings_dict.get("concurrency", 1),
            "browser": browser,
            "output": output,
            "highlight": highlight,
            "timeouts": timeouts,
        }
        # folder
        folder_js = d.get("folder", {})
        # progress
        progress_js = d.get("progress", {})
        return {
            "version": d.get("version"),
            "urls": urls_js,
            "images": images_js,
            "folder": folder_js,
            "prompt": prompt_js,
            "settings": settings_js,
            "progress": progress_js,
            "run_state": d.get("run_state"),
            "jobs": d.get("jobs", []),
        }

    def _emit_arena_state(self):
        try:
            js_state = self._arena_to_js()
            payload = json.dumps(js_state, ensure_ascii=False)
            self.arena_state_updated.emit(payload)
            prog = js_state.get("progress", {}).copy()
            prog["run_state"] = getattr(self, "_run_state", "idle")
            self.progress_updated.emit(json.dumps(prog, ensure_ascii=False))
        except Exception as e:
            log.warning(f"emit arena state failed: {e}")

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

    @Slot(result=str)
    def get_app_state(self):
        theme = self.config.get_state("theme", "dark")
        grid_layout = self.config.get_state("grid_layout", None)
        window_states = self.config.get_state("window_states", None)
        hist, idx = self.undo_service.history()
        payload = {
            "theme": theme,
            "state": {
                "grid_layout": grid_layout,
                "window_states": window_states,
                "undo_history": hist,
                "undo_history_index": idx,
            }
        }
        return json.dumps(payload, ensure_ascii=False)

    @Slot(str, result=bool)
    def set_theme(self, theme: str):
        self.config.set_state(theme=theme)
        self._log(f"Theme set to {theme}", "info")
        return True

    @Slot(result=str)
    def get_grid_layout(self):
        raw = self.config.get_state("grid_layout", None)
        if not isinstance(raw, str) or not raw:
            return ""
        payload, err = canonical_grid_payload(raw)
        return payload if not err else ""

    @Slot(str, result=bool)
    def save_grid_layout(self, layout_json: str):
        payload, err = canonical_grid_payload(layout_json or "")
        if err:
            self._log(f"Grid layout rejected: {err}", "warn")
            self.grid_layout_persisted.emit(False)
            return False
        self.config.set_state(grid_layout=payload)
        self.grid_layout_changed.emit(payload)
        self.grid_layout_persisted.emit(True)
        try:
            self.undo_service.push("grid", payload)
            self._emit_undo_state()
        except Exception:
            pass
        return True

    @Slot(result=str)
    def reset_grid_layout(self):
        payload = default_payload()
        self.config.set_state(grid_layout=payload, window_states={"closed": [], "minimized": []})
        self.grid_layout_changed.emit(payload)
        self.grid_layout_persisted.emit(True)
        self._log("Grid layout reset to default", "info")
        try:
            self.undo_service.push("grid", payload)
            self.undo_service.push("window_states", {"closed": [], "minimized": []})
            self._emit_undo_state()
        except Exception:
            pass
        return payload

    @Slot(result=str)
    def get_window_states(self):
        raw = self.config.get_state("window_states", None)
        if not isinstance(raw, dict):
            return ""
        closed = [i for i in raw.get("closed", []) if isinstance(i, str) and i in WINDOW_IDS]
        minimized = [i for i in raw.get("minimized", []) if isinstance(i, str) and i in WINDOW_IDS and i not in closed]
        return json.dumps({"closed": closed, "minimized": minimized}, ensure_ascii=False)

    @Slot(str, result=bool)
    def save_window_states(self, states_json: str):
        try:
            data = json.loads(states_json or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(data, dict):
            return False
        closed = [i for i in data.get("closed", []) if isinstance(i, str) and i in WINDOW_IDS]
        minimized = [i for i in data.get("minimized", []) if isinstance(i, str) and i in WINDOW_IDS and i not in closed]
        payload = {"closed": closed, "minimized": minimized}
        self.config.set_state(window_states=payload)
        try:
            self.undo_service.push("window_states", payload)
            self._emit_undo_state()
        except Exception:
            pass
        return True

    @Slot(result=str)
    def list_window_presets(self):
        presets = self.config.window_presets.list_presets()
        payload = json.dumps(presets, ensure_ascii=False)
        self.window_preset_list_updated.emit(payload)
        return payload


    def _extract_tree_from_grid(self, g, parsed):
        # ideal-size: 10 lines reason=extract tree case
        if "tree" not in g or not isinstance(g["tree"], dict):
            return None, None
        tree = g["tree"]
        ver = g.get("version") or parsed.get("v") or 4
        cand = json.dumps({"v": ver, "tree": tree}, ensure_ascii=False, separators=(",",":"))
        tp, err = canonical_grid_payload(cand)
        if err:
            return None, None
        return tree, tp

    def _extract_payload_from_grid(self, g):
        # ideal-size: 7 lines reason=extract payload case
        if "payload" not in g or not isinstance(g["payload"], str):
            return None, None
        tp, err = canonical_grid_payload(g["payload"])
        if err:
            return None, None
        data = json.loads(tp)
        return data.get("tree"), tp

    def _extract_from_portable(self, parsed: dict):
        # ideal-size: 12 lines reason=delegates to tree/payload helpers
        try:
            if not isinstance(parsed, dict):
                return None, None, None, None
            if "grid" not in parsed or not isinstance(parsed["grid"], dict):
                return None, None, None, None
            g = parsed["grid"]
            ws = parsed.get("window_states")
            tree, payload = self._extract_tree_from_grid(g, parsed)
            if payload:
                return tree, payload, ws, parsed
            tree, payload = self._extract_payload_from_grid(g)
            if payload:
                return tree, payload, ws, parsed
            return None, None, None, None
        except Exception:
            return None, None, None, None

    def _parse_preset_input(self, grid_json: str):
        # ideal-size: 18 lines reason=parses multiple input formats
        if not grid_json:
            return None, None, None, None, None
        try:
            parsed = json.loads(grid_json)
        except Exception as e:
            return None, None, None, None, f"bad JSON {e}"
        if not isinstance(parsed, dict):
            return None, None, None, None, "payload must be object"
        tree, payload, ws, doc = self._extract_from_portable(parsed)
        if payload:
            return tree, payload, ws, doc, None
        if "v" in parsed and "tree" in parsed:
            tp, err = canonical_grid_payload(grid_json)
            if not err:
                data = json.loads(tp)
                return data.get("tree"), tp, None, None, None
            return None, None, None, None, err
        return None, None, None, None, None

    def _build_preset_doc(self, name: str, payload: str, info: dict):
        # ideal-size: 20 lines reason=build final preset document from info dict
        data = json.loads(payload)
        tree = info.get("tree") or data.get("tree")
        ws = info.get("ws")
        incoming = info.get("incoming")
        count = len(leaf_ids(tree)) if tree else 0
        if not ws:
            ws = self.config.get_state("window_states", {"closed": [], "minimized": []})
            if incoming and isinstance(incoming.get("window_states"), dict):
                ws = incoming["window_states"]
        if incoming and isinstance(incoming, dict) and incoming.get("format") == "chat-v-bot.window-preset":
            doc = incoming.copy()
            doc["name"] = name
            doc["grid"] = {"payload": payload, "window_count": count, "tree": tree, "type": doc.get("grid", {}).get("type", "sash-tree"), "version": data.get("v", 4), "sizes_unit": "percent"}
            doc["window_states"] = ws
            doc["updated_at"] = datetime.utcnow().isoformat() + "Z"
            doc["app_version"] = doc.get("app_version", "arena-1.0")
        else:
            doc = {"name": name, "grid": {"payload": payload, "window_count": count, "tree": tree}, "window_states": ws, "updated_at": datetime.utcnow().isoformat() + "Z", "app_version": "arena-1.0"}
        return doc

    @Slot(str, str, result=str)
    def save_window_preset(self, name: str, grid_json: str):
        try:
            tree, payload, ws, incoming, err = self._parse_preset_input(grid_json)
            if not payload:
                payload, err = canonical_grid_payload(grid_json or self.get_grid_layout() or default_payload())
            if err and not payload:
                return json.dumps({"ok": False, "error": err})
            if not payload:
                return json.dumps({"ok": False, "error": "invalid grid payload"})
            info = {"tree": tree, "ws": ws, "incoming": incoming}
            doc = self._build_preset_doc(name, payload, info)
            self.config.window_presets.save_preset(name, doc)
            self.list_window_presets()
            count = doc.get("grid", {}).get("window_count", 0)
            self._log(f"Window preset saved: {name} ({count} windows)", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            import traceback
            traceback.print_exc()
            return json.dumps({"ok": False, "error": str(e)})


    @Slot(str, result=str)
    def load_window_preset(self, name: str):
        # Pure getter: returns the stored portable doc for the JS preview →
        # confirm → apply flow (no server-side apply; that would rearrange
        # the grid behind the preview modal before the user confirms).
        doc = self.config.window_presets.load_preset(name)
        if not doc:
            return json.dumps({"ok": False, "error": f"preset {name} not found"})
        try:
            grid = doc.get("grid", {})
            tree = grid.get("tree") if isinstance(grid, dict) else None
            if not isinstance(tree, dict):
                return json.dumps({"ok": False, "error": "unsupported window preset format or schema version"})
            ver = grid.get("version", GRID_VERSION)
            _, err = canonical_grid_payload(json.dumps({"v": ver, "tree": tree}))
            if err:
                return json.dumps({"ok": False, "error": err})
            self._log(f"Window preset loaded: {name}", "success")
            return json.dumps(doc, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_window_preset(self, name: str):
        ok = self.config.window_presets.delete_preset(name)
        if ok:
            self.list_window_presets()
            self._log(f"Window preset deleted: {name}", "info")
            return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def export_window_preset(self, name: str):
        doc = self.config.window_presets.load_preset(name)
        if not doc:
            return json.dumps({"ok": False, "error": "not found"})
        try:
            if QFileDialog is None:
                # headless fallback: export to config folder
                path = Path("config") / f"{name}_window.json"
                with path.open("w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            else:
                folder = QFileDialog.getExistingDirectory(None, "Export window preset")
                if not folder:
                    return json.dumps({"ok": False, "cancelled": True})
                path = Path(folder) / f"{name}.json"
                with path.open("w", encoding="utf-8") as f:
                    json.dump(doc, f, indent=2, ensure_ascii=False)
            self._exported_paths[name] = str(path)
            self._log(f"Window preset exported to {path}", "success")
            return json.dumps({"ok": True, "path": str(path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def import_window_preset(self):
        try:
            if QFileDialog is None:
                return json.dumps({"ok": False, "error": "No file dialog in headless mode"})
            file_path, _ = QFileDialog.getOpenFileName(None, "Import window preset", "", "JSON (*.json)")
            if not file_path:
                return json.dumps({"ok": False, "cancelled": True})
            with open(file_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            name = doc.get("name") or Path(file_path).stem
            grid = doc.get("grid", {})
            payload = grid.get("payload")
            if payload:
                _, err = canonical_grid_payload(payload)
                if err:
                    return json.dumps({"ok": False, "error": f"invalid grid: {err}"})
            self.config.window_presets.save_preset(name, doc)
            self.list_window_presets()
            self._log(f"Window preset imported: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=bool)
    def show_window_preset_in_folder(self, name: str):
        path = self._exported_paths.get(name) or str(self.config.window_presets.path)
        self._log(f"Preset folder: {path}", "info")
        return True

    @Slot(result=str)
    def get_arena_state(self):
        js_state = self._arena_to_js()
        return json.dumps(js_state, ensure_ascii=False)

    @Slot(str, result=str)
    def get_image_thumbnail(self, img_id: str):
        """Return base64 thumbnail — non-blocking to avoid mouse freeze.

        Previously did PIL sync in Qt main thread for 80 images -> freeze.
        Now: cache hit returns immediately; miss schedules background thread
        and returns pending with file:// fallback, then emits thumbnail_ready.
        """
        try:
            if img_id in self._thumb_cache:
                cached = self._thumb_cache[img_id]
                return json.dumps({"ok": True, "id": img_id, "data_url": cached, "cached": True}, ensure_ascii=False)

            target = None
            for im in self.state.images:
                if im.id == img_id:
                    target = im
                    break
            if not target:
                return json.dumps({"ok": False, "error": "not found"})

            p = Path(target.absolute_path)
            if not p.exists():
                return json.dumps({"ok": False, "error": "file not exists"})

            if img_id in self._thumb_in_progress:
                return json.dumps({"ok": False, "pending": True, "id": img_id, "fallback_url": f"file://{p}"}, ensure_ascii=False)

            # Phase 2: delegate to thumbnail_service (pure, no Qt)
            from .services.thumbnail_service import generate_thumbnail_data_url

            def _gen_thumb():
                res = generate_thumbnail_data_url(p, size=96, quality=80)
                res["id"] = img_id
                return res

            def _on_done(fut):
                try:
                    res = fut.result()
                    if res.get("ok") and res.get("data_url"):
                        self._thumb_cache[img_id] = res["data_url"]
                        try:
                            payload = json.dumps(res, ensure_ascii=False)
                            self.thumbnail_ready.emit(img_id, payload)
                        except Exception:
                            pass
                    self._thumb_in_progress.discard(img_id)
                except Exception:
                    self._thumb_in_progress.discard(img_id)

            if self._thumb_executor:
                self._thumb_in_progress.add(img_id)
                try:
                    fut = self._thumb_executor.submit(_gen_thumb)
                    fut.add_done_callback(_on_done)
                except Exception:
                    self._thumb_in_progress.discard(img_id)
                    res = _gen_thumb()
                    if res.get("ok") and res.get("data_url"):
                        self._thumb_cache[img_id] = res["data_url"]
                    return json.dumps(res, ensure_ascii=False)
                return json.dumps({"ok": False, "pending": True, "id": img_id, "fallback_url": f"file://{p}"}, ensure_ascii=False)
            else:
                res = _gen_thumb()
                if res.get("ok") and res.get("data_url"):
                    self._thumb_cache[img_id] = res["data_url"]
                return json.dumps(res, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    @Slot(str, result=str)
    def reveal_in_explorer(self, path_str: str):
        """Open file in Explorer/Finder — btn to open this file in explorer (not link)."""
        try:
            import platform, subprocess, os
            p = Path(path_str)
            if not p.exists():
                # try parent exists for output not yet created
                if p.parent.exists():
                    p = p.parent
                else:
                    return json.dumps({"ok": False, "error": f"Path does not exist: {path_str}"})
            system = platform.system()
            try:
                if system == "Windows":
                    # Use explorer /select for file, or open folder
                    if p.is_file():
                        # explorer /select,"path" — need to handle spaces
                        subprocess.Popen(f'explorer /select,"{p}"')
                    else:
                        os.startfile(str(p))  # type: ignore
                elif system == "Darwin":
                    if p.is_file():
                        subprocess.Popen(["open", "-R", str(p)])
                    else:
                        subprocess.Popen(["open", str(p)])
                else:
                    # Linux: xdg-open parent or file
                    if p.is_file():
                        subprocess.Popen(["xdg-open", str(p.parent)])
                    else:
                        subprocess.Popen(["xdg-open", str(p)])
                self._log(f"📁 Revealed in Explorer: {path_str}", "info")
                return json.dumps({"ok": True, "path": str(p)})
            except Exception as e:
                return json.dumps({"ok": False, "error": str(e)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def copy_path_to_clipboard(self, path_str: str):
        """Copy file path to clipboard — second option copy link to file. Fixed: was not copying."""
        try:
            # Try Qt clipboard — most reliable in QWebEngine
            clipboard = None
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    clipboard = app.clipboard()
            except Exception:
                pass
            if clipboard is None:
                try:
                    from PySide6.QtGui import QGuiApplication
                    app2 = QGuiApplication.instance()
                    if app2 is not None:
                        clipboard = app2.clipboard()
                except Exception:
                    pass
            if clipboard is not None:
                try:
                    from PySide6.QtGui import QClipboard
                    # Windows path like F:\Creative Cloud Files\... with spaces must be copied verbatim
                    clipboard.setText(path_str, mode=QClipboard.Clipboard)
                    try:
                        clipboard.setText(path_str, mode=QClipboard.Selection)
                    except Exception:
                        pass
                    # Ensure clipboard holds text
                    self._log(f"📋 Copied to clipboard: {path_str}", "info")
                    return json.dumps({"ok": True, "path": path_str, "method": "qt"})
                except Exception as e_qt:
                    # Fall through to subprocess fallback
                    self._log(f"Qt clipboard failed {e_qt}, trying subprocess", "warn")

            # Fallback subprocess — handles Windows clip, mac pbcopy, Linux xclip/xsel
            import subprocess, platform
            system = platform.system()
            if system == "Windows":
                # clip expects UTF-16? Use UTF-8 and shell, also try powershell Set-Clipboard
                try:
                    # Primary: clip
                    subprocess.run("clip", input=path_str.encode("utf-8"), check=True, shell=True)
                    self._log(f"📋 Copied via clip: {path_str}", "info")
                    return json.dumps({"ok": True, "path": path_str, "fallback": "clip"})
                except Exception:
                    # Secondary: powershell Set-Clipboard — handles spaces and Unicode better
                    try:
                        # Escape single quotes for powershell
                        ps_escaped = path_str.replace("'", "''")
                        ps_cmd = f"Set-Clipboard -Value '{ps_escaped}'"
                        subprocess.run(["powershell", "-Command", ps_cmd], check=True)
                        self._log(f"📋 Copied via powershell: {path_str}", "info")
                        return json.dumps({"ok": True, "path": path_str, "fallback": "powershell"})
                    except Exception as e_ps:
                        return json.dumps({"ok": False, "error": f"clip/powershell failed {e_ps}", "path": path_str})
            elif system == "Darwin":
                subprocess.run("pbcopy", input=path_str.encode("utf-8"), check=True)
                self._log(f"📋 Copied via pbcopy: {path_str}", "info")
                return json.dumps({"ok": True, "path": path_str, "fallback": "pbcopy"})
            else:
                # Linux try xclip/xsel
                try:
                    subprocess.run(["xclip", "-selection", "clipboard"], input=path_str.encode("utf-8"), check=True)
                    self._log(f"📋 Copied via xclip: {path_str}", "info")
                    return json.dumps({"ok": True, "path": path_str, "fallback": "xclip"})
                except Exception:
                    try:
                        subprocess.run(["xsel", "--clipboard", "--input"], input=path_str.encode("utf-8"), check=True)
                        self._log(f"📋 Copied via xsel: {path_str}", "info")
                        return json.dumps({"ok": True, "path": path_str, "fallback": "xsel"})
                    except Exception as e_x:
                        return json.dumps({"ok": False, "error": f"xclip/xsel failed {e_x}", "path": path_str})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e), "path": path_str})

    @Slot(str, result=str)
    def add_url(self, url: str):
        url = url.strip()
        if not url:
            return json.dumps({"ok": False, "error": "empty URL"})
        if not (url.startswith("http://") or url.startswith("https://")):
            return json.dumps({"ok": False, "error": "URL must start with http:// or https://"})
        for u in self.state.urls:
            if u.url == url:
                return json.dumps({"ok": False, "error": "URL already exists"})
        # push undo before change? We'll push after with new state
        item = UrlRow.create(url, enabled=True)
        self.state.urls.append(item)
        self._save_arena()
        # push urls snapshot to undo
        try:
            js_urls = self._arena_to_js()["urls"]
            self.undo_service.push("urls", js_urls)
            self._emit_undo_state()
        except Exception:
            pass
        return json.dumps({"ok": True, "id": item.id})

    def _push_urls_undo(self):
        try:
            js_urls = self._arena_to_js()["urls"]
            self.undo_service.push("urls", js_urls)
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, result=str)
    def remove_url(self, url_id: str):
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id != url_id]
        if len(self.state.urls) == before:
            return json.dumps({"ok": False, "error": "not found"})
        self._save_arena()
        self._push_urls_undo()
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def toggle_url(self, url_id: str):
        for u in self.state.urls:
            if u.id == url_id:
                u.enabled = not u.enabled
                self._save_arena()
                self._push_urls_undo()
                return json.dumps({"ok": True, "enabled": u.enabled})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, str, result=str)
    def edit_url(self, url_id: str, new_url: str):
        new_url = new_url.strip()
        if not new_url:
            return json.dumps({"ok": False, "error": "empty URL"})
        for u in self.state.urls:
            if u.id == url_id:
                u.url = new_url
                u.last_status = "unchecked"
                u.error = None
                self._save_arena()
                self._push_urls_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def test_url(self, url_id: str):
        for u in self.state.urls:
            if u.id == url_id:
                if u.url.startswith("http"):
                    u.last_status = "ready"
                    u.last_checked = datetime.utcnow().isoformat() + "Z"
                    self._save_arena()
                    return json.dumps({"ok": True, "status": "ready"})
                else:
                    u.last_status = "error"
                    u.error = "Invalid URL"
                    self._save_arena()
                    return json.dumps({"ok": False, "error": "Invalid URL"})
        return json.dumps({"ok": False, "error": "not found"})

    def _push_folder_undo(self):
        try:
            self.undo_service.push("folder", self.state.folder.copy())
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, result=str)
    def pick_folder(self, start_dir: str):
        if QFileDialog is None:
            return json.dumps({"ok": False, "error": "No file dialog"})
        start = (start_dir or "").strip()
        if not start or not Path(start).is_dir():
            last = (self.state.folder.get("root_path", "") or "").strip()
            start = last if last and Path(last).is_dir() else ""
        folder = QFileDialog.getExistingDirectory(None, "Select image folder", start)
        if not folder:
            return json.dumps({"ok": False, "cancelled": True})
        self.state.folder["root_path"] = folder
        self._save_arena()
        self._push_folder_undo()
        return json.dumps({"ok": True, "path": folder})

    @Slot(str, result=str)
    def set_folder_path(self, path: str):
        p = Path(path)
        if not p.exists() or not p.is_dir():
            return json.dumps({"ok": False, "error": "Folder does not exist"})
        self.state.folder["root_path"] = str(p)
        self._save_arena()
        self._push_folder_undo()
        return json.dumps({"ok": True, "path": str(p)})

    @Slot(result=str)
    def scan_folder(self):
        """Non-blocking scan to avoid UI freeze on mouse clicks."""
        if getattr(self, '_scan_in_progress', False):
            return json.dumps({"ok": False, "pending": True, "error": "scan already in progress"})
        root = self.state.folder.get("root_path", "")
        if not root:
            return json.dumps({"ok": False, "error": "No folder set"})
        root_path = Path(root)
        if not root_path.exists():
            return json.dumps({"ok": False, "error": "Folder does not exist"})

        from .services.scan_service import scan_folder_pure

        def _do_scan():
            try:
                supported = set(self.state.folder.get("supported_types", [".png",".jpg",".jpeg",".webp"]))
                ignore_ai = self.state.folder.get("ignore_ai_suffix", True)
                scanned = scan_folder_pure(root_path, supported, ignore_ai)
                added = self._merge_scanned(scanned)
                self.state.recalculate_progress()
                self._save_arena()
                self._log(f"Scanned {len(scanned)} images, {added} new", "success")
            except Exception as e:
                self._log(f"Scan failed: {e}", "error")
            finally:
                self._scan_in_progress = False

        # Schedule in thread pool — return pending immediately to avoid freeze
        try:
            self._scan_in_progress = True
            self._log(f"🔍 Scanning folder {root_path}… (non-blocking)", "info")
            if self._thumb_executor:
                self._thumb_executor.submit(_do_scan)
            else:
                import threading
                threading.Thread(target=_do_scan, daemon=True).start()
            return json.dumps({"ok": True, "pending": True, "count": 0, "message": "scan started non-blocking"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def scan_folder_new_batch(self):
        """Clear queue then scan — non-blocking to avoid freeze."""
        try:
            try:
                self._push_queue_undo()
            except Exception:
                pass
            cleared = len(self.state.images)
            self.state.images = []
            self.state.jobs = []
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"🗑 Cleared {cleared} old — scanning new batch non-blocking", "warn")

            root = self.state.folder.get("root_path", "")
            if not root:
                return json.dumps({"ok": False, "error": "No folder set", "cleared": cleared})
            root_path = Path(root)
            if not root_path.exists():
                return json.dumps({"ok": False, "error": "Folder does not exist", "cleared": cleared})

            from .services.scan_service import scan_folder_pure

            def _do_scan_new():
                try:
                    supported = set(self.state.folder.get("supported_types", [".png",".jpg",".jpeg",".webp"]))
                    ignore_ai = self.state.folder.get("ignore_ai_suffix", True)
                    scanned = scan_folder_pure(root_path, supported, ignore_ai)
                    for s in scanned:
                        img = ImageItem.from_scan_dict(s, selected=False)
                        self.state.images.append(img)
                    self.state.recalculate_progress()
                    self._save_arena()
                    self._log(f"🗑 New batch: cleared {cleared} old, scanned {len(scanned)} new images", "warn")
                except Exception as e:
                    self._log(f"New batch scan failed: {e}", "error")
                finally:
                    self._scan_in_progress = False

            self._scan_in_progress = True
            if self._thumb_executor:
                self._thumb_executor.submit(_do_scan_new)
            else:
                import threading
                threading.Thread(target=_do_scan_new, daemon=True).start()
            return json.dumps({"ok": True, "pending": True, "cleared": cleared, "message": "new batch scan started non-blocking"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _push_queue_undo(self):
        try:
            js_images = self._arena_to_js()["images"]
            self.undo_service.push("queue", js_images)
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, bool, result=str)
    def set_image_selected(self, img_id: str, selected: bool):
        for img in self.state.images:
            if img.id == img_id:
                img.selected = bool(selected)
                if selected and img.status == "skipped":
                    img.status = "pending"
                self.state.recalculate_progress()
                self._save_arena()
                self._push_queue_undo()
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(bool, str, result=str)
    def bulk_select(self, selected: bool, filter_status: str):
        count = 0
        for img in self.state.images:
            if filter_status == "all" or img.status == filter_status:
                img.selected = bool(selected)
                count += 1
        self.state.recalculate_progress()
        self._save_arena()
        self._push_queue_undo()
        return json.dumps({"ok": True, "count": count})

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
    def clear_images(self):
        # alias for clear_queue for compatibility
        return self.clear_queue()

    @Slot(result=str)
    def drop_ai_suffix(self):
        """Drop _AI: strip the suffix from filenames in the picker folder."""
        return self._run_folder_ai("strip")

    @Slot(result=str)
    def keep_only_ai_files(self):
        """Only _AI: delete non-_AI images in the picker folder."""
        return self._run_folder_ai("only")

    def _merge_scanned(self, scanned) -> int:
        """Merge scan dicts into the queue; returns added count."""
        existing = {img.relative_path: img for img in self.state.images}
        added = 0
        for s in scanned:
            rel = s["relative_path"]
            if rel not in existing:
                self.state.images.append(ImageItem.from_scan_dict(s, selected=False))
                added += 1
            else:
                e = existing[rel]
                e.size = s["size"]
                e.mtime = s["mtime"]
                e.absolute_path = s["absolute_path"]
        return added

    def _run_folder_ai(self, mode: str) -> str:
        """Disk _AI op on the picker folder; refuses mid-run. Pending JSON."""
        if getattr(self, "_run_state", "idle") != "idle":
            return json.dumps({"ok": False, "error": "stop the run first"})
        if getattr(self, '_scan_in_progress', False):
            return json.dumps({"ok": False, "pending": True, "error": "scan already in progress"})
        root = self.state.folder.get("root_path", "")
        if not root:
            return json.dumps({"ok": False, "error": "No folder set"})
        root_path = Path(root)
        if not root_path.exists():
            return json.dumps({"ok": False, "error": "Folder does not exist"})
        try:
            self._scan_in_progress = True
            self._log(f"Folder {'Only _AI' if mode == 'only' else 'Drop _AI'} in {root_path}...", "warn")
            self._submit_folder_ai(root_path, set(self.state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"])), mode)
        except Exception as e:
            self._scan_in_progress = False
            return json.dumps({"ok": False, "error": str(e)})
        return json.dumps({"ok": True, "pending": True})

    def _submit_folder_ai(self, root_path, exts, mode) -> None:
        """Run the folder _AI worker off the UI thread."""
        if self._thumb_executor:
            self._thumb_executor.submit(self._folder_ai_worker, root_path, exts, mode)
        else:
            import threading
            threading.Thread(target=self._folder_ai_worker, args=(root_path, exts, mode), daemon=True).start()

    def _folder_ai_worker(self, root_path, exts, mode) -> None:
        """Rename/delete _AI files on disk, sync queue. Off UI thread."""
        try:
            from app.core.folder_ai import delete_non_ai_images, strip_ai_suffixes
            if mode == "only":
                deleted, errors = delete_non_ai_images(root_path, exts)
                self._drop_missing_queue_images(root_path, deleted)
                self._log(f"Only _AI: deleted {len(deleted)} files from {root_path}", "warn")
            else:
                pairs, skipped, errors = strip_ai_suffixes(root_path, exts)
                self._rename_queue_images(root_path, pairs)
                self._log(f"Drop _AI: renamed {len(pairs)}, skipped {skipped} in {root_path}", "warn")
            for err in errors[:3]:
                self._log(str(err), "warn")
            self.state.recalculate_progress()
            self._save_arena()
        except Exception as e:
            self._log(f"Folder _AI op failed: {e}", "error")
        finally:
            self._scan_in_progress = False

    def _drop_missing_queue_images(self, root_path, deleted) -> None:
        """Forget queue entries whose files were deleted."""
        try:
            gone = {str(Path(root_path, r).resolve()) for r in deleted}
            self.state.images = [i for i in self.state.images if i.absolute_path not in gone]
        except Exception:
            pass

    def _rename_queue_images(self, root_path, pairs) -> None:
        """Point queue entries at renamed files (stats preserved)."""
        try:
            from app.utils.hashing import fingerprint_from_path_stat
            by_old = {str(Path(root_path, old).resolve()): new for old, new in pairs}
            for img in self.state.images:
                new_rel = by_old.get(img.absolute_path)
                if not new_rel:
                    continue
                img.relative_path = new_rel
                img.absolute_path = str(Path(root_path, new_rel).resolve())
                img.filename = Path(new_rel).name
                img.base_name = Path(new_rel).stem
                img.fingerprint = fingerprint_from_path_stat(new_rel, img.size, img.mtime)
        except Exception:
            pass

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

    def _push_prompt_undo(self, tmpl: str):
        try:
            self.undo_service.push("prompt", tmpl)
            self._emit_undo_state()
        except Exception:
            pass

    @Slot(str, result=str)
    def set_prompt(self, template: str):
        self.state.prompt["user_prompt"] = template
        self._save_arena()
        self._push_prompt_undo(template)
        return json.dumps({"ok": True})

    @Slot(str, result=str)
    def save_settings(self, settings_json: str):
        try:
            data = json.loads(settings_json)
            # Map to AppSettings structure
            if "timeout_seconds" in data:
                self.state.settings.timeouts["page_load"] = int(data["timeout_seconds"])
            if "generation_timeout" in data:
                # User-configurable waiting max time — up to 2 min+ as requested
                gt = int(data["generation_timeout"])
                # Clamp 30-3600 seconds (user wants to set timeout in win settings, allow up to 1h)
                gt = max(30, min(3600, gt))
                self.state.settings.timeouts["generation"] = gt
                self._log(f"Generation timeout set to {gt}s (waiting max time)", "info")
                # Also sync to watcher win settings — generation timeout
                try:
                    self.config.set_state(watcher_generation_timeout_sec=gt)
                    if self._watcher:
                        self._watcher.update_config(generation_timeout_sec=gt)
                except Exception:
                    pass
            if "max_retries" in data:
                self.state.settings.retries["max_attempts"] = int(data["max_retries"])
            if "naming_suffix" in data:
                self.state.settings.output["suffix"] = data["naming_suffix"]
            if "supported_types" in data:
                self.state.folder["supported_types"] = data["supported_types"]
                self.state.settings.supported_types = data["supported_types"]
            if "overwrite" in data:
                self.state.settings.output["overwrite"] = bool(data["overwrite"])
            if "highlight_duration" in data:
                self.state.settings.highlight["duration_seconds"] = int(data["highlight_duration"])
                self.config.set_state(highlight_duration=int(data["highlight_duration"]))
            # Also allow watcher timeouts from settings win if provided (user wants timeout in win settings)
            if "watcher_captcha_timeout_sec" in data:
                try:
                    ct = max(10, min(3600, int(data["watcher_captcha_timeout_sec"])))
                    self.config.set_state(watcher_captcha_timeout_sec=ct)
                    if self._watcher:
                        self._watcher.update_config(captcha_timeout_sec=ct)
                    self._log(f"Watcher captcha timeout set to {ct}s (user win setting)", "info")
                except Exception:
                    pass
            if "watcher_generation_timeout_sec" in data:
                try:
                    gt2 = max(30, min(3600, int(data["watcher_generation_timeout_sec"])))
                    self.config.set_state(watcher_generation_timeout_sec=gt2)
                    if self._watcher:
                        self._watcher.update_config(generation_timeout_sec=gt2)
                    self._log(f"Watcher generation timeout set to {gt2}s (user win setting)", "info")
                except Exception:
                    pass
            self._save_arena()
            try:
                self.undo_service.push("settings", self._arena_to_js()["settings"])
                self._emit_undo_state()
            except Exception:
                pass
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def export_preset(self, name: str):
        try:
            preset_path = Path("config") / f"{name}.json"
            save_preset(self.state, preset_path)
            return json.dumps({"ok": True, "path": str(preset_path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def import_preset(self):
        try:
            if QFileDialog is None:
                return json.dumps({"ok": False, "error": "No file dialog"})
            file_path, _ = QFileDialog.getOpenFileName(None, "Import preset JSON", "config", "JSON (*.json)")
            if not file_path:
                return json.dumps({"ok": False, "cancelled": True})
            data = load_preset(Path(file_path))
            if "urls" in data:
                self.state.urls = [UrlRow(**u) for u in data["urls"]]
            if "folder" in data:
                self.state.folder.update(data["folder"])
            if "prompt" in data:
                self.state.prompt.update(data["prompt"])
            if "settings" in data:
                # settings dict from preset is already AppSettings as dict
                s = data["settings"]
                # handle both old and new formats
                if isinstance(s, dict):
                    # if it has timeouts etc, update
                    if "timeouts" in s:
                        self.state.settings.timeouts.update(s["timeouts"])
                    if "output" in s:
                        self.state.settings.output.update(s["output"])
                    if "highlight" in s:
                        self.state.settings.highlight.update(s["highlight"])
            self.state.recalculate_progress()
            self._save_arena()
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- run controls — real implementation via CDP ----
    def _get_selected_images(self):
        return [img for img in self.state.images if img.selected and img.status in ("pending","failed","selected","needs_review","processing")]

    def _get_enabled_urls(self):
        return [u for u in self.state.urls if u.enabled]

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

    async def _settle_boundary_captcha(self, ctrl, primary_tab_id, correlation_id, source):
        """F4: captcha at a phase boundary — auto-solve or wait, then record."""
        await self._settle_captcha_at(ctrl, primary_tab_id, correlation_id, source)

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

    # ---- watcher win — passive recheck every x ms for generating icon or captcha ----
    def _get_watcher_cdp_controller(self):
        """Get CDP controller for watcher — creates CDPArenaController from current cdp client."""
        try:
            if not self.cdp or not getattr(self.cdp, 'is_connected', False):
                return None
            from app.browser.cdp_arena import CDPArenaController
            return CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
        except Exception:
            return None

    def _on_watcher_state(self, payload: dict):
        """Callback from watcher service — emit to UI."""
        try:
            import json as _json
            self.watcher_status.emit(_json.dumps(payload, ensure_ascii=False))
            # Also log important transitions
            status = payload.get("status","")
            if status in ("waiting_captcha", "waiting_generation"):
                kind = payload.get("waiting_kind","")
                dur = payload.get("waiting_duration",0)
                if dur % 10 == 0 or dur < 5:  # log every 10s and first 5s
                    self._log(f"👁️ Watcher {status}: {kind} for {dur}s", "warn" if "captcha" in status else "info")
        except Exception as e:
            try:
                self._log(f"Watcher state emit failed: {e}", "warn")
            except Exception:
                pass

    @Slot(result=str)
    def get_watcher_config(self):
        try:
            if self._watcher:
                # Ensure task is running if enabled and loop now available
                try:
                    self._watcher.ensure_task()
                except Exception:
                    pass
                cfg = self._watcher.get_config()
            else:
                cfg = {
                    "enabled": bool(self.config.get_state("watcher_enabled", False)),
                    "check_interval_ms": int(self.config.get_state("watcher_interval_ms", 2000)),
                    "captcha_timeout_sec": int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
                    "generation_timeout_sec": int(self.config.get_state("watcher_generation_timeout_sec", 600)),
                    "auto_pause_jobs": bool(self.config.get_state("watcher_auto_pause", True)),
                }
            return json.dumps(cfg, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(str, result=str)
    def set_watcher_config(self, cfg_json: str):
        try:
            import json as _json
            data = _json.loads(cfg_json or "{}")
            # Validate
            enabled = bool(data.get("enabled", False))
            interval = int(data.get("check_interval_ms", 2000))
            interval = max(500, min(interval, 30000))  # 0.5s to 30s
            captcha_to = int(data.get("captcha_timeout_sec", 300))
            captcha_to = max(10, min(captcha_to, 3600))
            gen_to = int(data.get("generation_timeout_sec", 600))
            gen_to = max(30, min(gen_to, 3600))
            auto_pause = bool(data.get("auto_pause_jobs", True))

            # Persist to session
            self.config.set_state(
                watcher_enabled=enabled,
                watcher_interval_ms=interval,
                watcher_captcha_timeout_sec=captcha_to,
                watcher_generation_timeout_sec=gen_to,
                watcher_auto_pause=auto_pause,
            )

            # Update watcher service
            if self._watcher:
                self._watcher.update_config(
                    enabled=enabled,
                    check_interval_ms=interval,
                    captcha_timeout_sec=captcha_to,
                    generation_timeout_sec=gen_to,
                    auto_pause_jobs=auto_pause,
                )
            else:
                # Create watcher if not exists and enabled
                if enabled:
                    from app.services.watcher import WatcherService, WatcherConfig
                    cfg_obj = WatcherConfig(
                        enabled=enabled,
                        check_interval_ms=interval,
                        captcha_timeout_sec=captcha_to,
                        generation_timeout_sec=gen_to,
                        auto_pause_jobs=auto_pause,
                    )
                    self._watcher = WatcherService(
                        config=cfg_obj,
                        cdp_controller_getter=lambda: self._get_watcher_cdp_controller(),
                        job_runner_getter=lambda: self,
                        logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
                    )
                    self._watcher.add_callback(lambda p: self._on_watcher_state(p))
                    self._watcher.start()

            self._log(f"Watcher config saved: enabled={enabled} interval={interval}ms captcha_to={captcha_to}s gen_to={gen_to}s", "success")
            return json.dumps({"ok": True, "config": {
                "enabled": enabled,
                "check_interval_ms": interval,
                "captcha_timeout_sec": captcha_to,
                "generation_timeout_sec": gen_to,
                "auto_pause_jobs": auto_pause,
            }}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def start_watcher(self):
        try:
            if not self._watcher:
                from app.services.watcher import WatcherService, WatcherConfig
                cfg = WatcherConfig(
                    enabled=True,
                    check_interval_ms=int(self.config.get_state("watcher_interval_ms", 2000)),
                    captcha_timeout_sec=int(self.config.get_state("watcher_captcha_timeout_sec", 300)),
                    generation_timeout_sec=int(self.config.get_state("watcher_generation_timeout_sec", 600)),
                    auto_pause_jobs=bool(self.config.get_state("watcher_auto_pause", True)),
                )
                self._watcher = WatcherService(
                    config=cfg,
                    cdp_controller_getter=lambda: self._get_watcher_cdp_controller(),
                    job_runner_getter=lambda: self,
                    logger=lambda msg, level="info": self._log(f"[Watcher] {msg}", level)
                )
                self._watcher.add_callback(lambda p: self._on_watcher_state(p))
            self._watcher.update_config(enabled=True)
            self.config.set_state(watcher_enabled=True)
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def stop_watcher(self):
        try:
            if self._watcher:
                self._watcher.update_config(enabled=False)
            self.config.set_state(watcher_enabled=False)
            self._log("Watcher stopped by user", "warn")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_watcher_state(self):
        try:
            if not self._watcher:
                return json.dumps({"status": "idle", "enabled": False}, ensure_ascii=False)
            state = self._watcher.get_state()
            cfg = self._watcher.get_config()
            return json.dumps({**state, "config": cfg}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(result=str)
    def clear_watcher_overlay(self):
        try:
            if self._watcher:
                import asyncio
                # Schedule clear
                cdp = self._get_watcher_cdp_controller()
                if cdp:
                    self._schedule_coro(cdp.hide_watcher_overlay())
                self._schedule_coro(self._watcher.force_clear())
            else:
                cdp = self._get_watcher_cdp_controller()
                if cdp:
                    self._schedule_coro(cdp.hide_watcher_overlay())
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def check_watcher_now(self):
        try:
            if not self._watcher:
                return json.dumps({"ok": False, "error": "watcher not initialized"})
            # Schedule immediate check
            self._schedule_coro(self._watcher.check_once())
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- PagePool — multi-page steady/busy tracking ----
    @Slot(result=str)
    def get_page_pool_status(self):
        try:
            if not self._page_pool:
                return json.dumps({"total": 0, "steady": 0, "busy": 0, "cooling": 0, "free": 0, "pages": []})
            try:
                from app.services.cooldown_service import refresh_expired
                for _tid in refresh_expired(self._page_pool):
                    self._log(f"✅ Page {_tid[:12]} cooldown expired — STEADY ready", "success")
            except Exception:
                pass
            snap = self._page_pool.status_snapshot()
            self.page_pool_updated.emit(json.dumps(snap, ensure_ascii=False))
            self._persist_cooldowns()
            return json.dumps(snap, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(result=str)
    def clear_page_pool(self):
        try:
            if not self._page_pool:
                return json.dumps({"ok": True, "cleared": 0})
            snap = self._page_pool.status_snapshot()
            count = snap.get("total", 0)
            # Clear internal dicts
            try:
                self._page_pool._pages.clear()
                self._page_pool._clients.clear()
                self._page_pool._controllers.clear()
            except Exception:
                pass
            try:
                from app.persistence.cooldown_store import save_entries
                save_entries(self._cooldowns_path(), {})
            except Exception:
                pass
            self._emit_pool_status()
            self._log(f"Page pool cleared {count} pages", "warn")
            return json.dumps({"ok": True, "cleared": count})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def connect_page_pool(self, ws_url: str):
        try:
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            if not ws_url:
                return json.dumps({"ok": False, "error": "empty ws_url"})
            self._log(f"🔗 Adding tab to pool {ws_url[:80]}… steady", "info")
            self._schedule_coro(self._do_connect_page_pool(ws_url))
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def disconnect_page_pool(self, tab_id: str):
        try:
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            ok = self._page_pool.remove_page(tab_id)
            self._emit_pool_status()
            if ok:
                self._log(f"Pool page {tab_id[:12]} removed", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_cooldown_config(self):
        try:
            from app.core.cooldown import config_to_dict
            from app.services.cooldown_service import load_config
            cfg = load_config(self.config.get_state)
            return json.dumps({"ok": True, "config": config_to_dict(cfg)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def set_cooldown_config(self, cfg_json: str):
        try:
            from app.core.cooldown import clamp_seconds
            data = json.loads(cfg_json or "{}")
            enabled = bool(data.get("enabled", True))
            min_s = clamp_seconds(data.get("min_seconds", 300), 300)
            pen_s = clamp_seconds(data.get("captcha_penalty_seconds", 900), 900)
            rl_s = clamp_seconds(data.get("rate_limit_penalty_seconds", 1800), 1800)
            self.config.set_state(cooldown_enabled=enabled, cooldown_min_seconds=min_s,
                                  cooldown_captcha_penalty_seconds=pen_s,
                                  cooldown_rate_limit_penalty_seconds=rl_s)
            self._log(f"Cooldown set: enabled={enabled} min={min_s // 60}m penalty={pen_s // 60}m per captcha limit={rl_s // 60}m", "success")
            return json.dumps({"ok": True, "config": {"enabled": enabled, "min_seconds": min_s,
                                                      "captcha_penalty_seconds": pen_s,
                                                      "rate_limit_penalty_seconds": rl_s}}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # ---- 2Captcha solving (opt-in, RULE 20 as amended 2026-09-17) ----
    # WebChannel constraint: slots must live on this QObject (wire format);
    # the lazy getter keeps __init__ untouched. Net line delta of this
    # change is negative (inline captcha blocks replaced by choke point).

    def _captcha_service(self):
        """Lazy CaptchaService (key store + stats + solver); config dir = session store dir."""
        svc = getattr(self, "_captcha_service_obj", None)
        if svc is None:
            from app.services.captcha import CaptchaService
            svc = self._captcha_service_obj = CaptchaService(str(self.config.dir), self._log)
        return svc

    @Slot(str, result=str)
    def set_captcha_settings(self, payload_json: str):
        """Save 2Captcha key/enable/timeout; key stays local (masked in reply)."""
        try:
            data = json.loads(payload_json or "{}")
            key = str(data.get("api_key", "") or "").strip()
            enabled = bool(data.get("enabled", False))
            timeout = int(data.get("solve_timeout_sec", 180))
            result = self._captcha_service().apply_settings(key, enabled, timeout)
            self._log(f"🔐 2Captcha settings saved (key={'set' if key else 'empty'}, enabled={result['enabled']}, timeout={timeout}s)", "success")
            if result["enabled"]:
                asyncio.create_task(self._captcha_service().refresh_balance())
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def get_captcha_status(self):
        """Key mask + balance + last error; raw key never leaves the store."""
        try:
            svc = self._captcha_service()
            if svc.status_payload().get("has_key"):
                asyncio.create_task(svc.refresh_balance())  # fire-and-forget, next call shows it
            return json.dumps({"ok": True, **svc.status_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_captcha_stats(self):
        """Local solve counters + auto success rate + balance (API stat)."""
        try:
            return json.dumps({"ok": True, **self._captcha_service().stats_payload()}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    async def _settle_captcha_at(self, ctrl, tab_id, correlation_id, source):
        """Gate on visible, then auto-solve or wait; raise on stop (shared by 4 sites)."""
        try:
            if not await ctrl.is_security_dialog_visible():
                return
        except Exception:
            return
        from app.services.captcha import CaptchaCtx, handle_captcha
        stop = lambda: bool(self._stop_reason(tab_id)) if self._run_stop_requested(tab_id) else False
        def log(msg, level="info"):
            self._log(f"[{correlation_id}] {msg}", level)
        outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=self._page_pool, bridge=self,
                                                  tab_id=tab_id, source=source, stop=stop, log=log))
        if outcome.status == "stopped":
            raise RuntimeError(f"{self._stop_reason(tab_id)} during CAPTCHA at {source}")

    @Slot(str, result=str)
    def reset_page_cooldown(self, tab_id: str):
        try:
            from app.services.cooldown_service import is_stuck_status, reset_cooldown
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            page = self._page_pool.get_page(tab_id)
            if page is None:
                return json.dumps({"ok": False, "error": "unknown tab"})
            if is_stuck_status(page.status):
                return self._reset_stuck_page(tab_id, page)
            if reset_cooldown(self._page_pool, tab_id):
                self._emit_pool_status()
                self._log(f"♻️ Cooldown reset for {(tab_id or '')[:12]} — tab ready", "success")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "unknown tab"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def stop_tab_job(self, tab_id: str):
        """Abort the live job on this tab; it fails as Aborted."""
        try:
            from app.services.cooldown_service import request_tab_abort
            if request_tab_abort(self._page_pool, tab_id):
                self._log(f"⛔ Stop requested for job on {(tab_id or '')[:12]}", "warn")
                self._emit_pool_status()
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "no live job on this tab"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _reset_stuck_page(self, tab_id: str, page) -> str:
        """Force-free a stuck page; refuses while its own job is alive."""
        from app.services.cooldown_service import force_reset_page, tab_has_live_job
        was = getattr(page.status, "value", page.status)
        if tab_has_live_job(self._page_pool, tab_id):
            self._log(f"⚠ Reset refused for {(tab_id or '')[:12]} — job still running on this tab; stop it first", "warn")
            return json.dumps({"ok": False, "error": "job still running on this tab — stop it first"})
        if force_reset_page(self._page_pool, tab_id):
            self._emit_pool_status()
            self._log(f"♻️ Stuck {was} reset for {(tab_id or '')[:12]} (no run active) — tab ready, fix and run again", "success")
            return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "unknown tab"})

    @Slot(str, int, result=str)
    def set_page_cooldown(self, tab_id: str, seconds: int):
        try:
            from app.core.cooldown import format_remaining
            from app.services.cooldown_service import edit_cooldown
            if not self._page_pool:
                return json.dumps({"ok": False, "error": "pool not initialized"})
            if edit_cooldown(self._page_pool, tab_id, int(seconds or 0)):
                self._emit_pool_status()
                left = format_remaining(int(seconds or 0))
                self._log(f"⏳ Cooldown for {(tab_id or '')[:12]} set to {left}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "unknown tab or job running"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    async def _do_connect_page_pool(self, ws_url: str):
        try:
            from app.browser.cdp_client import CDPClient
            from app.browser.cdp_arena import CDPArenaController
            from app.browser.page_status import PageInfo
            import re
            m = re.search(r'/devtools/page/([^/]+)$', ws_url)
            tab_id = m.group(1) if m else ws_url
            host = self._page_pool._host if self._page_pool else "127.0.0.1"
            port = self._page_pool._port if self._page_pool else 9222
            client = CDPClient(host=host, port=port)
            ok = await client.connect(ws_url)
            if not ok:
                self._log(f"❌ Pool connect failed {ws_url[:80]}", "error")
                return
            ctrl = CDPArenaController(client, log_callback=lambda msg: self._log(msg, "info"))
            live_title, live_url = await self._resolve_tab_info(tab_id, ws_url)
            info = PageInfo(tab_id=tab_id, ws_url=ws_url, title=live_title or tab_id, url=live_url or "")
            self._page_pool.add_page(info)
            self._page_pool.register_client(tab_id, client, ctrl)
            self._restore_page_state(tab_id)
            self._emit_pool_status()
            total, free = self._page_pool.get_counts()
            self._log(f"✅ Pool added {tab_id[:12]} steady — {info.title[:40]} — total {total} free {free}", "success")
            if total >= 2:
                self._log(f"✅ {total} tabs in pool ready for parallel — 2+ images will dispatch to different webpages", "success")
        except Exception as e:
            self._log(f"Pool connect exception {e}", "error")

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
            await ctrl.highlight_selector(textarea_primary(), color="#FF0000", duration_ms=duration_ms, caption=f"Image {img_id[:8]}" if img_id else "Clicked element")
            self.highlight_rect.emit(json.dumps({"x":200,"y":200,"width":320,"height":180,"duration":duration,"label":f"Image {img_id}" if img_id else "Clicked element"}))
        except Exception as e:
            self._log(f"Highlight failed: {e}", "warn")

    async def _do_run_batch(self):
        """Run the batch via the extracted orchestrator (W1.5)."""
        from app.services.batch_orchestrator import run_batch
        await run_batch(self)





    # ---- undo system ----
    def _emit_undo_state(self):
        try:
            hist, idx = self.undo_service.history()
            can_undo = idx >= 0
            can_redo = idx < len(hist) - 1
            payload = json.dumps({
                "history": hist,
                "index": idx,
                "canUndo": can_undo,
                "canRedo": can_redo,
                "count": len(hist),
            }, ensure_ascii=False)
            self.undo_state_changed.emit(payload)
            self.history_changed.emit()
        except Exception as e:
            log.warning(f"emit undo state failed: {e}")

    @Slot(result=str)
    def get_undo_history(self):
        hist, idx = self.undo_service.history()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    @Slot(str, str, result=bool)
    def push_global_history(self, kind: str, value_json: str):
        try:
            # parse value
            try:
                value = json.loads(value_json) if value_json else None
            except json.JSONDecodeError:
                # for grid, value_json is already canonical payload string; keep raw
                value = value_json
            # validate grid
            if kind == "grid":
                payload, err = canonical_grid_payload(value if isinstance(value, str) else json.dumps(value))
                if err:
                    return False
                value = payload
            # push
            self.undo_service.push(kind, value)
            self._remember_global_edit(kind, value)
            self._emit_undo_state()
            return True
        except Exception as e:
            log.warning(f"push_global_history failed: {e}")
            return False

    def _remember_global_edit(self, kind, value):
        """Apply a pushed global edit to live state (dispatch by kind)."""
        handler = _UNDO_REMEMBER_HANDLERS.get(kind)
        if handler is None:
            return  # unknown kinds are a silent no-op (characterized)
        try:
            handler(self, value)
        except Exception as e:
            log.warning(f"_remember_global_edit {kind} failed: {e}")

    def _remember_grid(self, value):
        self.config.set_state(grid_layout=value)
        self.grid_layout_changed.emit(value)
        self.grid_layout_persisted.emit(True)

    def _remember_window_states(self, value):
        if isinstance(value, dict):
            self.config.set_state(window_states=value)

    def _remember_urls(self, value):
        if isinstance(value, list):
            self.state.urls = _js_urls_to_rows(value)
            self._save_arena()

    def _remember_folder(self, value):
        if isinstance(value, dict):
            self.state.folder.update(value)
            self._save_arena()

    def _remember_queue(self, value):
        if isinstance(value, list):
            sel_map = {img.get("id"): img.get("selected") for img in value}
            for im in self.state.images:
                if im.id in sel_map:
                    im.selected = bool(sel_map[im.id])
            self.state.recalculate_progress()
            self._save_arena()

    def _remember_prompt(self, value):
        if isinstance(value, str):
            self.state.prompt["user_prompt"] = value
            self._save_arena()
        elif isinstance(value, dict):
            tmpl = value.get("template") or value.get("user_prompt") or ""
            self.state.prompt["user_prompt"] = tmpl
            self._save_arena()

    def _remember_settings(self, value):
        if isinstance(value, dict):
            self.state.settings.timeouts.update(value.get("timeouts", {}))
            self.state.settings.output.update(value.get("output", {}))
            self.state.settings.highlight.update(value.get("highlight", {}))
            if "supported_types" in value:
                self.state.folder["supported_types"] = value["supported_types"]
            self._save_arena()

    def _remember_action_blocks(self, value):
        if isinstance(value, list):
            try:
                self.config.set_state(action_blocks=value)
                self.action_blocks_updated.emit(json.dumps(value, ensure_ascii=False))
                self._log(f"↩ Remember action_blocks ({len(value)} blocks)", "info")
            except Exception as e:
                log.warning(f"remember action_blocks failed: {e}")

    def _remember_arena(self, value):
        if isinstance(value, dict):
            try:
                if isinstance(value.get("urls"), list) and value["urls"] and "url" in value["urls"][0]:
                    self.state.urls = [UrlRow(
                        id=u.get("id"), url=u.get("url"), enabled=u.get("enabled", True),
                        last_status=u.get("status", "unchecked"), error=u.get("last_error")
                    ) for u in value["urls"]]
                if "folder" in value:
                    self.state.folder.update(value["folder"])
                if "prompt" in value:
                    tmpl = value["prompt"].get("template") if isinstance(value["prompt"], dict) else value["prompt"]
                    if tmpl:
                        self.state.prompt["user_prompt"] = tmpl
                self.state.recalculate_progress()
                self._save_arena()
            except Exception as e:
                log.warning(f"remember arena edit failed: {e}")

    def _apply_undo_entry(self, entry):
        """Apply one undo entry to live state (dispatch by kind)."""
        if not entry or not isinstance(entry, dict):
            return False
        kind = entry.get("kind")
        value = entry.get("value")
        try:
            handler = _UNDO_APPLY_HANDLERS.get(kind)
            if handler is None:
                self._log(f"↩ Undo {kind} (no specific handler)", "info")
            else:
                handler(self, value)
            return True
        except Exception as e:
            log.warning(f"_apply_undo_entry {kind} failed: {e}")
            return False

    def _apply_grid(self, value):
        if isinstance(value, str):
            self.config.set_state(grid_layout=value)
            self.grid_layout_changed.emit(value)
            self.grid_layout_persisted.emit(True)
            self._log(f"↩ Undo grid layout", "info")

    def _apply_window_states(self, value):
        if isinstance(value, dict):
            self.config.set_state(window_states=value)
            self._log(f"↩ Undo window states", "info")

    def _apply_urls(self, value):
        if isinstance(value, list):
            self.state.urls = _js_urls_to_rows(value)
            self._save_arena()
            self._log(f"↩ Undo URLs ({len(value)} items)", "info")

    def _apply_folder(self, value):
        if isinstance(value, dict):
            self.state.folder = value
            self._save_arena()
            self._log(f"↩ Undo folder", "info")

    def _apply_queue(self, value):
        if isinstance(value, list):
            sel_map = {img.get("id"): img for img in value}
            for im in self.state.images:
                if im.id in sel_map:
                    js = sel_map[im.id]
                    im.selected = bool(js.get("selected", im.selected))
                    im.status = js.get("status", im.status)
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"↩ Undo queue selection", "info")

    def _apply_prompt(self, value):
        tmpl = value if isinstance(value, str) else (value.get("template") if isinstance(value, dict) else "")
        self.state.prompt["user_prompt"] = tmpl
        self._save_arena()
        self._log(f"↩ Undo prompt", "info")

    def _apply_settings(self, value):
        if isinstance(value, dict):
            for key in ("timeouts", "output", "highlight"):
                if key in value:
                    getattr(self.state.settings, key).update(value[key])
            if "supported_types" in value:
                self.state.folder["supported_types"] = value["supported_types"]
                self.state.settings.supported_types = value["supported_types"]
            self._save_arena()
            self._log(f"↩ Undo settings", "info")

    def _apply_action_blocks(self, value):
        # NOTE: historically the first of two duplicated elif branches ran
        # here and logged "Remember action_blocks" — quirk kept (characterized).
        if isinstance(value, list):
            try:
                self.config.set_state(action_blocks=value)
                self.action_blocks_updated.emit(json.dumps(value, ensure_ascii=False))
                self._log(f"↩ Remember action_blocks ({len(value)} blocks)", "info")
            except Exception as e:
                log.warning(f"apply action_blocks undo failed: {e}")

    def _apply_arena(self, value):
        if isinstance(value, dict):
            try:
                if "urls" in value:
                    self.state.urls = [UrlRow(
                        id=u.get("id"), url=u.get("url"), enabled=u.get("enabled", True),
                        last_status=u.get("status", "unchecked"), error=u.get("last_error")
                    ) for u in value["urls"]]
                if "folder" in value:
                    self.state.folder.update(value["folder"])
                if "prompt" in value:
                    tmpl = value["prompt"].get("template") if isinstance(value["prompt"], dict) else str(value["prompt"])
                    self.state.prompt["user_prompt"] = tmpl
                self.state.recalculate_progress()
                self._save_arena()
                self._log(f"↩ Undo arena snapshot", "info")
            except Exception as e:
                log.warning(f"apply arena undo failed: {e}")


    @Slot(result=str)
    def undo(self):
        result = self.undo_service.undo()
        if not result:
            self._log("⚠ Nothing to undo", "warn")
            self._emit_undo_state()
            return "null"
        hist, idx = self.undo_service.history()
        if idx == -1:
            # undo to empty — restore default/empty for the undone kind
            undone = result.get("undone") or result
            undone_kind = (undone.get("kind") if isinstance(undone, dict) else None) or result.get("kind")
            try:
                if undone_kind == "grid":
                    payload = default_payload()
                    self.config.set_state(grid_layout=payload)
                    self.grid_layout_changed.emit(payload)
                    self.grid_layout_persisted.emit(True)
                    self._log("↩ Undo grid → default", "info")
                elif undone_kind == "window_states":
                    empty_ws = {"closed": [], "minimized": []}
                    self.config.set_state(window_states=empty_ws)
                    self._log("↩ Undo window states → empty", "info")
                elif undone_kind == "urls":
                    self.state.urls = []
                    self._save_arena()
                    self._log("↩ Undo urls → empty", "info")
                elif undone_kind == "folder":
                    self.state.folder = {"root_path": "", "supported_types": [".png",".jpg",".jpeg",".webp"], "ignore_ai_suffix": True}
                    self._save_arena()
                    self._log("↩ Undo folder → empty", "info")
                elif undone_kind == "queue":
                    # keep images but clear selection? For empty we keep as is and log
                    self._log(f"↩ Undo {undone_kind} → empty", "info")
                elif undone_kind == "prompt":
                    self.state.prompt["user_prompt"] = ""
                    self._save_arena()
                    self._log("↩ Undo prompt → empty", "info")
                elif undone_kind == "settings":
                    self._log(f"↩ Undo {undone_kind} → empty", "info")
                else:
                    self._log(f"↩ Undo {undone_kind or result.get('kind')} → empty", "info")
            except Exception as e:
                log.warning(f"undo empty handling failed: {e}")
        else:
            # apply the current pointer's entry (previous state)
            current_entry = hist[idx] if 0 <= idx < len(hist) else None
            if current_entry:
                self._apply_undo_entry(current_entry)
            else:
                self._apply_undo_entry(result)
        self._emit_undo_state()
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def redo(self):
        result = self.undo_service.redo()
        if not result:
            self._log("⚠ Nothing to redo", "warn")
            self._emit_undo_state()
            return "null"
        self._apply_undo_entry(result)
        self._emit_undo_state()
        self._log(f"↪ Redo {result.get('kind')}", "success")
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def get_stack_history(self):
        hist, idx = self.undo_service.stack_projection()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    @Slot(str)
    def push_stack_history(self, stack_json: str):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if isinstance(blocks, list):
            self.undo_service.push_stack(blocks)
            self._emit_undo_state()

    @Slot(str, int)
    def save_stack_history(self, history_json: str, index: int):
        try:
            hist = json.loads(history_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(hist, list):
            return
        if not isinstance(index, int):
            index = -1
        self.undo_service.set_stack_projection(hist, index)
        self._emit_undo_state()

    @Slot(result=str)
    def undo_stack(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") in ("prompt","arena","urls","settings","queue","folder"):
                return json.dumps(result.get("value"), ensure_ascii=False)
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def redo_stack(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") in ("prompt","arena","urls","settings","queue","folder"):
                return json.dumps(result.get("value"), ensure_ascii=False)
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def undo_grid_layout(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") == "grid":
                return result.get("value") or "null"
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def redo_grid_layout(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") == "grid":
                return result.get("value") or "null"
            return "null"
        except Exception:
            return "null"

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
                    # Heuristic: if coro is _do_run_batch, keep reference
                    if hasattr(coro, 'cr_code') and coro.cr_code.co_name == '_do_run_batch':
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

    @Slot(result=str)
    def get_tabs(self):
        """Non-blocking: always schedule async fetch in thread, return pending immediately.
        Previous sync fetch_tabs_sync did blocking DNS/socket in UI thread causing freeze.
        """
        if not self.cdp:
            return json.dumps([], ensure_ascii=False)
        # Schedule async fetch in background thread, return pending instantly
        self._schedule_coro(self._do_fetch_tabs())
        return "pending"

    @Slot(result=str)
    def diagnose_chrome(self):
        """Non-blocking diagnose: schedule in thread, return pending, emit logs via signals.
        Previous sync version blocked UI for several seconds doing DNS + socket checks.
        """
        if not self.cdp:
            return json.dumps({"error": "CDP not available"}, ensure_ascii=False)
        self._log(f"🩺 Diagnosing Chrome remote debugging on {self.cdp._host}:{self.cdp._port}… (non-blocking)", "info")
        self._schedule_coro(self._do_diagnose_chrome())
        return "pending"

    async def _do_diagnose_chrome(self):
        try:
            # Run sync diagnose in threadpool to avoid blocking event loop
            import asyncio
            loop = asyncio.get_event_loop()
            diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
            self._log(diag.get("summary",""), "info" if "✅" in diag.get("summary","") else "warn")
            for chk in diag.get("checks", []):
                host = chk.get("host")
                if chk.get("port_open"):
                    self._log(f"  · {host}:{self.cdp._port} open — list: {chk.get('list_count')} tabs", "info")
                else:
                    self._log(f"  · {host}:{self.cdp._port} closed — {chk.get('list_error') or chk.get('version_error') or 'no response'}", "warn")
                for t in chk.get("tabs", [])[:5]:
                    self._log(f"    - {t.get('title','')[:60]} — {t.get('url','')}", "success")
            # Also emit tabs if found
            if diag.get("tabs"):
                try:
                    payload = json.dumps([{"id": t.get("id"), "title": t.get("title"), "url": t.get("url"), "ws_url": t.get("ws_url")} for t in diag.get("tabs", [])], ensure_ascii=False)
                    self.tabs_received.emit(payload)
                except Exception:
                    pass
        except Exception as e:
            err = f"Diagnose failed: {e}"
            self._log(err, "error")

    async def _do_fetch_tabs(self):
        try:
            tabs = await self.cdp.fetch_tabs()
            payload = json.dumps([{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs], ensure_ascii=False)
            self.tabs_received.emit(payload)
            if not tabs:
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
                    self._log(diag.get("summary",""), "warn")
                except Exception:
                    pass
        except Exception as e:
            self._log(f"❌ Tab fetch failed: {e}", "error")

    def _pooled_ids(self) -> set:
        """Ids currently in the pool; empty when pool is unavailable."""
        try:
            return set(self._page_pool._pages.keys())
        except Exception:
            return set()

    @Slot(str, result=str)
    def auto_connect_scan(self, source: str):
        """Non-blocking auto-connect scan: rows + pool follow open tabs."""
        if not self.cdp or not self._page_pool:
            return json.dumps({"ok": False, "error": "CDP or pool not ready"})
        if self._auto_scan_running:
            return "pending"
        self._schedule_coro(self._do_auto_connect_scan(source or "auto"))
        return "pending"

    def _prune_auto_rows(self, plan) -> int:
        """Drop auto-linked rows whose tabs vanished; returns removed count."""
        if not plan.remove:
            return 0
        gone = set(plan.remove)
        before = len(self.state.urls)
        self.state.urls = [u for u in self.state.urls if u.id not in gone]
        return before - len(self.state.urls)

    def _apply_auto_plan(self, plan) -> bool:
        """Claim/add/prune URL rows from the plan; True when rows changed."""
        by_id = {u.id: u for u in self.state.urls}
        changed = False
        for row_id, tab_id in plan.claim:
            row = by_id.get(row_id)
            if row is not None and not row.tab_id:
                row.tab_id = tab_id
                changed = True
        added = _add_missing_rows(self.state.urls, plan.add)
        pruned = self._prune_auto_rows(plan)
        changed = bool(added) or changed or pruned > 0
        if changed:
            # system action, reproducible by re-scan: no undo spam
            self._save_arena()
            self._emit_arena_state()
        return changed

    def _report_auto_plan(self, plan, revived: int, stale: list, source: str):
        """Pool emit + summary; manual scans always answer, auto only on change."""
        changed = plan.add or plan.claim or plan.connect or revived or stale or plan.remove
        if not changed:
            if source == "manual":
                self._log("🤖 Reparse: no changes — rows and pool already match open tabs", "info")
            return
        if plan.connect or revived or stale or plan.remove:
            self._emit_pool_status()
        self._log(f"🤖 Auto-connect: +{len(plan.add)} rows, {len(plan.claim)} linked, "
                  f"{len(plan.connect)} joined, {revived} revived, {len(stale)} stale, "
                  f"{len(plan.remove)} removed", "info")

    async def _join_new_tabs(self, sockets) -> None:
        """Pool-join each connectable tab; skips empty sockets."""
        for ws in sockets or []:
            if ws:
                await self._do_connect_page_pool(ws)

    def _auto_prune_allowed(self, tabs) -> bool:
        """Prune dead rows only with a healthy tab list and no live run."""
        if getattr(self, "_run_state", "idle") != "idle":
            return False
        return any(getattr(t, "id", "") or getattr(t, "ws_url", "") for t in tabs or [])

    def _plan_auto_sync(self, tabs, pattern, rows):
        """Plan the scan; attach safe row pruning when allowed."""
        from app.services.auto_connect import live_tab_keys, plan_auto_connect, prunable_row_ids
        plan = plan_auto_connect(tabs, pattern, rows, self._pooled_ids())
        if self._auto_prune_allowed(tabs):
            plan.remove = prunable_row_ids(rows, live_tab_keys(tabs))
        return plan

    async def _do_auto_connect_scan(self, source: str = "auto"):
        """Fetch tabs, sync rows + pool + presence; skips when busy."""
        if self._auto_scan_running:
            return
        self._auto_scan_running = True
        try:
            from app.services.auto_connect import sync_pool_presence
            tabs = await self.cdp.fetch_tabs()
            pattern = self.config.get_state("url_pattern", "arena.ai")
            rows, removed = _dedupe_state_rows(self.state.urls)
            if removed:  # legacy broken state: N rows on one tab -> keep one (I-33)
                self._log(f"🤖 Auto-connect: removed {removed} extra row(s) — their tab already has a row", "warn")
            plan = self._plan_auto_sync(tabs, pattern, rows)
            self._apply_auto_plan(plan)
            await self._join_new_tabs(plan.connect)
            live = {(t.id or t.ws_url) for t in tabs or []} - {""}
            revived, stale = sync_pool_presence(self._page_pool, live)
            self._report_auto_plan(plan, revived, stale, source)
        except Exception as e:
            self._log(f"Auto-connect scan skipped: {e}", "warn")
        finally:
            self._auto_scan_running = False

    def _popup_targets(self) -> list:
        """Titles of enabled rows with live pool tabs (deduped)."""
        titles, seen = [], set()
        try:
            pool = self._page_pool
            if not pool:
                return titles
            for u in self.state.urls:
                if not (u.enabled and u.tab_id) or u.tab_id in seen:
                    continue
                page = pool.get_page(u.tab_id)
                if page is None or not page.is_connected:
                    continue
                seen.add(u.tab_id)
                if page.title:
                    titles.append(page.title)
        except Exception:
            pass
        return titles

    @Slot(result=str)
    def popup_url_tabs(self):
        """Popup-on-top: raise OS windows of live URL tabs, tabs untouched."""
        if not self._page_pool:
            return json.dumps({"ok": False, "error": "pool not initialized"})
        self._schedule_coro(self._do_popup_url_tabs())
        return "pending"

    async def _do_popup_url_tabs(self):
        """Raise desktop windows of live URL tabs (no tab switching)."""
        from app.utils.win_popup import raise_window_titles
        targets = self._popup_targets()
        if not targets:
            self._log("⏫ Popup: no active URL tabs (need enabled + linked + connected)", "warn")
            return
        try:
            raised = raise_window_titles(targets)
        except Exception:
            raised = 0
        self._log(f"⏫ Popup: {raised}/{len(targets)} windows on top (tabs untouched)", "success")

    def _primary_ws(self) -> str:
        """Socket of the first live pool tab, else ''."""
        try:
            from app.services.auto_connect import pick_primary_ws
            pages = list(self._page_pool._pages.values()) if self._page_pool else []
            return pick_primary_ws(pages)
        except Exception:
            return ""

    async def _do_ensure_primary(self):
        """Passive primary retry: connect first live pool tab when down."""
        try:
            if not self.cdp or self.cdp.is_connected or self._ensure_running:
                return
            self._ensure_running = True
            try:
                ws = self._primary_ws()
                if ws and await self.cdp.connect(ws):
                    self._log("✅ Primary auto-connected — runs can start", "success")
                    self.connection_status.emit("connected")
            finally:
                self._ensure_running = False
        except Exception:
            pass

    @Slot(result=str)
    def ensure_primary_connected(self):
        """500ms passive tick: keep the primary tab connected."""
        if not self.cdp:
            return json.dumps({"ok": False})
        try:
            if self.cdp.is_connected:
                return json.dumps({"ok": True})
        except Exception:
            pass
        self._schedule_coro(self._do_ensure_primary())
        return "pending"

    @Slot(str)
    def connect_tab(self, ws_url: str):
        if not self.cdp:
            self._log("CDP client not available", "error")
            return
        # Debounce: if same ws_url requested within 1.5s, skip duplicate
        try:
            import time
            now = time.time()
            if ws_url == self._last_connect_ws and (now - self._last_connect_ts) < 1.5:
                log.debug(f"connect_tab debounced duplicate {ws_url[:60]}")
                return
            if self._connect_in_progress and ws_url == self._last_connect_ws:
                log.debug(f"connect_tab already in progress for {ws_url[:60]}, skipping")
                return
            self._last_connect_ws = ws_url
            self._last_connect_ts = now
        except Exception:
            pass
        self._log(f"🔗 Connecting to {ws_url[:120]}… (port {self.cdp._port}, host {self.cdp._host})", "info")
        self._schedule_coro(self._do_connect_tab(ws_url))

    async def _do_connect_tab(self, ws_url: str):
        self._connect_in_progress = True
        try:
            # If already connected to same tab, reuse — avoid disconnect/reconnect race
            try:
                if self.cdp and self.cdp.is_connected and self.cdp._current_tab_id:
                    import re
                    m = re.search(r'/devtools/page/([^/]+)$', ws_url)
                    if m and m.group(1) == self.cdp._current_tab_id:
                        self._log(f"✅ Already connected to {ws_url[:80]} (reuse)", "success")
                        self.connection_status.emit("connected")
                        return
            except Exception:
                pass
            ok = await self.cdp.connect(ws_url)
            if ok:
                self._log(f"✅ Connected to {ws_url[:80]} (tab {self.cdp._current_tab_id[:20]}…)", "success")
                self.connection_status.emit("connected")
                self._log(f"CDP session active on ws://{self.cdp._host}:{self.cdp._port}/devtools/page/{self.cdp._current_tab_id[:30]}", "info")
                # Also add to PagePool as steady page with dedicated client
                # Fix: previously pool reused self.cdp for all tabs, causing second tab to overwrite first and both jobs using same websocket -> Submit failed
                # Now create dedicated CDPClient per tab for pool, so 2+ tabs truly independent
                try:
                    if self._page_pool:
                        from app.browser.page_status import PageInfo
                        from app.browser.cdp_arena import CDPArenaController
                        from app.browser.cdp_client import CDPClient
                        import re as _re
                        m_id = _re.search(r'/devtools/page/([^/]+)$', ws_url)
                        tab_id = m_id.group(1) if m_id else getattr(self.cdp, '_current_tab_id', '') or ws_url
                        title = getattr(self.cdp, '_current_title', '') or ''
                        url = getattr(self.cdp, '_current_url', '') or ''
                        if not url or not title:
                            live_title, live_url = await self._resolve_tab_info(tab_id, ws_url)
                            title = title or live_title or tab_id
                            url = url or live_url
                        # Check if pool already has dedicated client for this tab_id
                        existing_client, _ = self._page_pool.get_clients(tab_id)
                        if existing_client and getattr(existing_client, 'is_connected', False):
                            # Update info only, keep existing dedicated client
                            info = PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url)
                            self._page_pool.add_page(info)
                            self._emit_pool_status()
                            self._log(f"📦 Pool: tab {tab_id[:12]} already has dedicated client steady (reuse)", "info")
                        else:
                            # Create dedicated client for pool (independent from self.cdp)
                            host = getattr(self.cdp, '_host', '127.0.0.1')
                            port = getattr(self.cdp, '_port', 9222)
                            dedicated = CDPClient(host=host, port=port)
                            ok2 = await dedicated.connect(ws_url)
                            if ok2:
                                info = PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url)
                                self._page_pool.add_page(info)
                                ctrl2 = CDPArenaController(dedicated, log_callback=lambda m: self._log(m, "info"))
                                self._page_pool.register_client(tab_id, dedicated, ctrl2)
                                self._emit_pool_status()
                                total, free = self._page_pool.get_counts()
                                self._log(f"📦 Pool: added tab {tab_id[:12]} steady with dedicated client — total {total} pages {free} free", "success")
                                if total >= 2:
                                    self._log(f"✅ {total} tabs in pool ready for parallel — when 2+ images selected, Run will dispatch to different webpages (steady/busy tracked, no double-send)", "success")
                            else:
                                # Fallback: use primary client if dedicated fails
                                info = PageInfo(tab_id=tab_id, ws_url=ws_url, title=title, url=url)
                                self._page_pool.add_page(info)
                                ctrl = CDPArenaController(self.cdp, log_callback=lambda m: self._log(m, "info"))
                                self._page_pool.register_client(tab_id, self.cdp, ctrl)
                                self._emit_pool_status()
                                total_f, _ = self._page_pool.get_counts() if self._page_pool else (0, 0)
                                self._log(f"📦 Pool: added primary tab {tab_id[:12]} steady (dedicated failed, using primary) — total {total_f}", "warn")
                            self._restore_page_state(tab_id)
                except Exception as e:
                    import traceback as _tb
                    self._log(f"Pool add primary failed: {e} {_tb.format_exc()[-500:]}", "warn")
            else:
                self._log(f"❌ Connect failed for {ws_url[:120]} — check Chrome still open on port {self.cdp._port}, try Diagnose", "error")
                self._log(f"💡 Tip: Ensure Chrome was started with --remote-debugging-port={self.cdp._port} --user-data-dir=... and that http://{self.cdp._host}:{self.cdp._port}/json/list shows JSON in browser", "warn")
                self.connection_status.emit("error")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-1000:]
            self._log(f"❌ Connect exception for {ws_url[:80]}: {e} — {tb}", "error")
            self.connection_status.emit("error")
        finally:
            self._connect_in_progress = False

    @Slot(str)
    def find_tab_by_url(self, query: str):
        """Non-blocking: schedule async matching in thread with debounce."""
        if not self.cdp:
            self._log("CDP not available", "error")
            return
        # Debounce: if same query within 1.0s, skip
        try:
            import time
            now = time.time()
            q = (query or "").strip()
            if q and q == self._last_find_query and (now - self._last_find_ts) < 1.0:
                log.debug(f"find_tab_by_url debounced duplicate {q[:60]}")
                return
            if self._find_in_progress:
                log.debug(f"find_tab_by_url already in progress, skipping {q[:60]}")
                return
            self._last_find_query = q
            self._last_find_ts = now
        except Exception:
            pass
        self._schedule_coro(self._do_find_tab(query))

    async def _do_find_tab(self, query: str):
        self._find_in_progress = True
        try:
            query = (query or "").strip()
            if not query:
                self._log("⚠ URL field empty", "warn")
                self.tab_match_result.emit(query, "[]")
                return
            try:
                tabs = await self.cdp.fetch_tabs()
                if not tabs:
                    try:
                        import asyncio
                        loop = asyncio.get_event_loop()
                        diag = await loop.run_in_executor(None, lambda: self.cdp.diagnose_sync())
                        self._log(diag.get("summary","⚠ No Chrome tabs found"), "warn")
                        self._log(f"💡 Fix: 1) Close ALL Chrome windows. 2) Run: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port={self.cdp._port} --user-data-dir=\"C:\\arena-images-chrome\" 3) Open https://arena.ai in that NEW Chrome window. 4) Click Diagnose. 5) Open http://{self.cdp._host}:{self.cdp._port}/json/list — you should see JSON.", "warn")
                    except Exception:
                        self._log(f"⚠ No Chrome tabs found — start Chrome with --remote-debugging-port={self.cdp._port} --user-data-dir=\"C:\\arena-images-chrome\"", "warn")
                    self.tab_match_result.emit(query, "[]")
                    return
                tab_dicts = [{"id": t.id, "title": t.title, "url": t.url, "ws_url": t.ws_url} for t in tabs]
                matches = best_matches(query, tab_dicts)
                if not matches:
                    self._log(f"❌ No tab matches “{query}”. Available: " + "; ".join(f"{t.title} — {t.url}" for t in tabs[:5]), "error")
                    self.tab_match_result.emit(query, "[]")
                    return
                for m in matches[:3]:
                    self._log(f"  · match ({m['kind']}): {m['title']} — {m['url']}", "success")
                self.tab_match_result.emit(query, json.dumps(matches, ensure_ascii=False))
            except Exception as e:
                self._log(f"❌ Tab matching failed: {e}", "error")
                self.tab_match_result.emit(query, "[]")
        finally:
            self._find_in_progress = False

    # URL bookmarks (from old app, now using arena_presets)
    @Slot(result=str)
    def get_url_presets(self):
        try:
            presets = self.config.presets.get_url_presets()
            return json.dumps(presets, ensure_ascii=False)
        except Exception:
            return "[]"

    @Slot(str)
    def add_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            self._log("⚠ URL field empty — nothing added", "warn")
            return
        try:
            if self.config.presets.add_url_preset(url):
                self._log(f"💾 URL bookmark added: {url}", "success")
            else:
                self._log(f"ℹ URL bookmark already exists: {url}", "info")
            payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
            self.url_presets_updated.emit(payload)
            self.presets_changed.emit("urls", payload)
        except Exception as e:
            self._log(f"Add bookmark failed: {e}", "error")

    @Slot(str)
    def remove_url_preset(self, url: str):
        try:
            if self.config.presets.remove_url_preset(url):
                self._log(f"🗑 URL bookmark removed: {url}", "warn")
            payload = json.dumps(self.config.presets.get_url_presets(), ensure_ascii=False)
            self.url_presets_updated.emit(payload)
            self.presets_changed.emit("urls", payload)
        except Exception as e:
            self._log(f"Remove bookmark failed: {e}", "error")

    @Slot(str)
    def set_last_url_preset(self, url: str):
        url = (url or "").strip()
        if not url:
            return
        self.config.set_state(last_url_preset=url)
        self._log(f"🔖 Bookmark remembered: {url}", "info")

    # Arena presets (full)
    @Slot(result=str)
    def list_arena_presets(self):
        try:
            presets = self.config.presets.list_arena_presets()
            payload = json.dumps(presets, ensure_ascii=False)
            self.presets_changed.emit("arena", payload)
            return payload
        except Exception as e:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_arena_preset(self, name: str):
        try:
            js_state = self._arena_to_js()
            cdp_cfg = {
                "host": self.config.get_state("cdp_host", "127.0.0.1"),
                "port": self.config.get_state("cdp_port", 9222),
                "user_data_dir": self.config.get_state("cdp_user_data_dir", "C:\\arena-images-chrome"),
                "extra_args": self.config.get_state("cdp_extra_args", ""),
            }
            # Include action blocks in preset
            try:
                action_blocks = self.config.get_state("action_blocks", None)
                if action_blocks is None:
                    from app.core.action_blocks import default_stack, stack_to_dicts
                    action_blocks = stack_to_dicts(default_stack())
            except Exception:
                action_blocks = []
            doc = {
                "name": name,
                "urls": js_state.get("urls", []),
                "folder": js_state.get("folder", {}),
                "prompt": js_state.get("prompt", {}),
                "settings": js_state.get("settings", {}),
                "images": js_state.get("images", []),
                "cdp": cdp_cfg,
                "action_blocks": action_blocks,
                "cooldown": {
                    "enabled": self.config.get_state("cooldown_enabled", True),
                    "min_seconds": self.config.get_state("cooldown_min_seconds", 300),
                    "captcha_penalty_seconds": self.config.get_state("cooldown_captcha_penalty_seconds", 900),
                    "rate_limit_penalty_seconds": self.config.get_state("cooldown_rate_limit_penalty_seconds", 1800),
                },
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "app_version": "arena-1.0",
            }
            self.config.presets.save_arena_preset(name, doc)
            self.list_arena_presets()
            self._log(f"Arena preset saved: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_arena_preset(self, name: str):
        try:
            doc = self.config.presets.load_arena_preset(name)
            if not doc:
                return json.dumps({"ok": False, "error": "not found"})
            # restore
            if "urls" in doc:
                self.state.urls = [UrlRow(
                    id=u.get("id", f"url_{i}"),
                    url=u.get("url",""),
                    enabled=u.get("enabled",True),
                    last_status=u.get("status","unchecked"),
                    error=u.get("last_error")
                ) for i, u in enumerate(doc.get("urls", []))]
            if "folder" in doc:
                self.state.folder.update(doc["folder"])
            if "prompt" in doc:
                tmpl = doc["prompt"].get("template") if isinstance(doc["prompt"], dict) else str(doc["prompt"])
                self.state.prompt["user_prompt"] = tmpl
            if "settings" in doc:
                s = doc["settings"]
                if isinstance(s, dict):
                    if "timeouts" in s:
                        self.state.settings.timeouts.update(s["timeouts"])
                    if "output" in s:
                        self.state.settings.output.update(s["output"])
                    if "highlight" in s:
                        self.state.settings.highlight.update(s["highlight"])
                    if "supported_types" in s:
                        self.state.folder["supported_types"] = s["supported_types"]
            if "cdp" in doc and isinstance(doc["cdp"], dict):
                c = doc["cdp"]
                host = c.get("host", "127.0.0.1")
                port = c.get("port", 9222)
                user_data_dir = c.get("user_data_dir", "C:\\arena-images-chrome")
                extra = c.get("extra_args", "")
                self.config.set_state(cdp_host=host, cdp_port=int(port), cdp_user_data_dir=user_data_dir, cdp_extra_args=extra)
                if self.cdp:
                    try:
                        self.cdp.set_host_port(host, int(port))
                    except Exception:
                        pass
            if "action_blocks" in doc and isinstance(doc["action_blocks"], list):
                try:
                    self.config.set_state(action_blocks=doc["action_blocks"])
                    self.action_blocks_updated.emit(json.dumps(doc["action_blocks"], ensure_ascii=False))
                    self._log(f"Restored {len(doc['action_blocks'])} action blocks from preset", "info")
                except Exception as e:
                    log.warning(f"Failed to restore action blocks from preset: {e}")
            if "cooldown" in doc and isinstance(doc["cooldown"], dict):
                try:
                    from app.core.cooldown import clamp_seconds
                    cd = doc["cooldown"]
                    self.config.set_state(
                        cooldown_enabled=bool(cd.get("enabled", True)),
                        cooldown_min_seconds=clamp_seconds(cd.get("min_seconds", 300), 300),
                        cooldown_captcha_penalty_seconds=clamp_seconds(cd.get("captcha_penalty_seconds", 900), 900),
                        cooldown_rate_limit_penalty_seconds=clamp_seconds(cd.get("rate_limit_penalty_seconds", 1800), 1800))
                    self._log("Restored cooldown settings from preset", "info")
                except Exception as e:
                    log.warning(f"Failed to restore cooldown from preset: {e}")
            self.state.recalculate_progress()
            self._save_arena()
            self._log(f"Arena preset loaded: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_arena_preset(self, name: str):
        try:
            if self.config.presets.delete_arena_preset(name):
                self.list_arena_presets()
                self._log(f"Arena preset deleted: {name}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    # Prompt presets
    @Slot(result=str)
    def list_prompt_presets(self):
        try:
            presets = self.config.presets.list_prompt_presets()
            return json.dumps(presets, ensure_ascii=False)
        except Exception:
            return "[]"

    @Slot(str, str, result=str)
    def save_prompt_preset(self, name: str, template: str):
        try:
            self.config.presets.save_prompt_preset(name, template)
            self._log(f"Prompt preset saved: {name}", "success")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_prompt_preset(self, name: str):
        try:
            doc = self.config.presets.load_prompt_preset(name)
            if not doc:
                return json.dumps({"ok": False, "error": "not found"})
            tmpl = doc.get("template","")
            self.state.prompt["user_prompt"] = tmpl
            self._save_arena()
            return json.dumps({"ok": True, "template": tmpl})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_prompt_preset(self, name: str):
        try:
            if self.config.presets.delete_prompt_preset(name):
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

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

    @Slot(str, result=str)
    def refresh_users(self):
        # compatibility with old app: just emit arena state
        self._emit_arena_state()
        return json.dumps({"ok": True})

# Undo dispatch tables (module level so unbound calls with stub selves work)
_UNDO_REMEMBER_HANDLERS = {
    "grid": Bridge._remember_grid, "window_states": Bridge._remember_window_states,
    "urls": Bridge._remember_urls, "folder": Bridge._remember_folder,
    "queue": Bridge._remember_queue, "prompt": Bridge._remember_prompt,
    "settings": Bridge._remember_settings, "action_blocks": Bridge._remember_action_blocks,
    "arena": Bridge._remember_arena,
}
_UNDO_APPLY_HANDLERS = {
    "grid": Bridge._apply_grid, "window_states": Bridge._apply_window_states,
    "urls": Bridge._apply_urls, "folder": Bridge._apply_folder,
    "queue": Bridge._apply_queue, "prompt": Bridge._apply_prompt,
    "settings": Bridge._apply_settings, "action_blocks": Bridge._apply_action_blocks,
    "arena": Bridge._apply_arena,
}

def _js_urls_to_rows(value):
    """JS url dicts -> UrlRow list (urls-kind shape: default ids, error fallback)."""
    return [UrlRow(
        id=u.get("id", f"url_{i}"),
        url=u.get("url", ""),
        enabled=u.get("enabled", True),
        last_status=u.get("status", "unchecked"),
        last_checked=u.get("last_checked"),
        error=u.get("last_error") or u.get("error")
    ) for i, u in enumerate(value)]

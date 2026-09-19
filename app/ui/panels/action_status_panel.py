"""Action Status Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
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


log = logging.getLogger("arena")


class JobStatusPanel:

    def _emit_job_action_status(self, job_id: str, block: Any, status: str, message: str = ""):
        """Emit job/block status WITHOUT a highlight rect (most call sites)."""
        self._emit_job_action(job_id, block, {"status": status, "message": message})

    def _emit_job_action_rect(self, job_id: str, block: Any, opts: dict):
        """Emit job/block status WITH a highlight rect.
        opts: status, message, rect (rect may be None -> behaves like plain)."""
        self._emit_job_action(job_id, block, opts)

    def _emit_job_action(self, job_id: str, block: Any, opts: dict):
        """Shared emit: payload + signal (+ highlight rect for running/success)."""
        try:
            block_id, block_name, color, highlight_ms = _job_block_meta(block)
            status, message, rect = opts.get("status", ""), opts.get("message", ""), opts.get("rect")
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
            if rect and status in ("running", "success"):
                self._emit_highlight_rect(rect, block_name, color, highlight_ms)
        except Exception as e:
            log.warning(f"emit job action status failed: {e}")

    def _emit_highlight_rect(self, rect: dict, block_name: Any, color: str, highlight_ms: Any):
        """Second channel: highlight_rect signal built from a block rect."""
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


def _job_block_meta(block: Any) -> tuple:
    """Normalize a block (str/dict/ActionBlock) to (id, display name, color, highlight ms)."""
    if isinstance(block, str):
        return block, block, "#FF0000", 2000
    block_id = getattr(block, 'id', '') or getattr(block, 'block_id', '') or str(block)
    block_name = getattr(block, 'display_name', None) or getattr(block, 'name', block_id)
    if callable(block_name):
        block_name = block_name()
    color = getattr(block, 'color', '#FF0000')
    highlight_ms = getattr(block, 'highlight_duration_ms', 2000)
    return block_id, block_name, color, highlight_ms

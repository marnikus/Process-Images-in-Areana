# ideal-size: ~350 lines reason=frozen 10-slot JS queue surface plus the module funcs each slot delegates to; splitting would scatter slot<->helper pairs that always change together (RULE 18.2)
"""Queue + scan panel — image queue, folder scan, queue file tools, folder-AI.

Owns 10 of the 12 scan/queue slots (R3) — `pick_folder`/`set_folder_path`
live in `queue_scan_folder.FolderPickMixin` (2026-10-02 bugfix: folder
shape normalisation) and are inherited here; thin slots delegate to module funcs;
OS/disk work lives in ui/services (file_service, folder_ai_service,
scan_service, thumbnail_service). The run-scope read model is
`core.run_scope.run_scope` (one predicate, I-44 — run_control imports it
directly). `clear_images` is the compat alias of run_control's
`clear_queue` (log packing table). Imports go panels -> services/core
only (Qt via qt_compat).
"""

import functools
import json
import threading
from pathlib import Path

from app.ui.qt_compat import Slot, clipboard_copy
from app.ui.panels.queue_scan_folder import FolderPickMixin, as_folder_dict
from app.services.live import feed
from app.ui.services import arena_serialize, undo_entries
from app.ui.services import file_service, folder_ai_service
from app.ui.services.scan_service import merge_scanned, scan_folder_pure, scan_summary
from app.ui.services.thumbnail_service import generate_thumbnail_data_url


def find_image(images, img_id: str):
    """Queue item by id (None when missing)."""
    for img in images:
        if img.id == img_id:
            return img
    return None


def apply_bulk_selection(images, selected: bool, filter_status: str) -> int:
    """Set selected on items matching the filter; returns count touched."""
    count = 0
    for img in images:
        if filter_status == "all" or img.status == filter_status:
            img.selected = bool(selected)
            count += 1
    return count


def resolve_scan_root(folder) -> tuple:
    """Picker folder or (None, error); shared scan/folder-AI guard."""
    root = as_folder_dict(folder).get("root_path", "")
    if not root:
        return None, "No folder set"
    root_path = Path(root)
    if not root_path.exists():
        return None, "Folder does not exist"
    return root_path, ""


def run_off_ui_thread(bridge, fn, *args) -> None:
    """Run worker `fn(bridge, *args)` off the UI thread.

    Thumb executor doubles as scan pool; else a daemon thread.
    """
    if bridge._thumb_executor:
        bridge._thumb_executor.submit(fn, bridge, *args)
    else:
        threading.Thread(target=fn, args=(bridge, *args), daemon=True).start()


def push_queue_undo(bridge) -> None:
    """Snapshot image queue to undo (best effort)."""
    try:
        js_images = arena_serialize.arena_to_js(bridge.state)["images"]
        bridge.undo_service.push("queue", js_images)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


# S4: the panel layer owns the undo push; services.live feed wakes it layer-legally.
feed.set_undo_hook(push_queue_undo)


def clear_queue_images(bridge) -> int:
    """Empty images+jobs (undoable); returns cleared count. No log/JSON."""
    count = len(bridge.state.images)
    push_queue_undo(bridge)                      # pre-push: undo restores the cleared list
    bridge.state.images = []
    bridge.state.jobs = []
    feed.commit_queue(bridge, "clear_queue", undo=False)
    return count


def run_scan_merge(bridge, root_path: Path) -> None:
    """Scan worker: merge into queue, save. Off UI thread."""
    try:
        supported = set(bridge.state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"]))
        ignore_ai = bridge.state.folder.get("ignore_ai_suffix", True)
        scanned = scan_folder_pure(root_path, supported, ignore_ai)
        added = merge_scanned(bridge.state.images, scanned)
        bridge.state.recalculate_progress()
        bridge._save_arena()
        bridge._log(*scan_summary(scanned, added))
    except Exception as e:
        bridge._log(f"Scan failed: {e}", "error")
    finally:
        bridge._scan_in_progress = False


def run_scan_new_batch(bridge, root_path: Path, cleared: int) -> None:
    """New-batch worker: queue was cleared, fill from scan. Off UI thread."""
    try:
        supported = set(bridge.state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"]))
        ignore_ai = bridge.state.folder.get("ignore_ai_suffix", True)
        scanned = scan_folder_pure(root_path, supported, ignore_ai)
        # Queue was cleared by the slot: merge appends all (selected=False),
        # identical to the original inline loop.
        added = merge_scanned(bridge.state.images, scanned)
        feed.commit_queue(bridge, "scan", undo=False)
        summary, _level = scan_summary(scanned, added)  # a new batch is destructive: always warn
        bridge._log(f"🗑 New batch: cleared {cleared} old — {summary}", "warn")
    except Exception as e:
        bridge._log(f"New batch scan failed: {e}", "error")
    finally:
        bridge._scan_in_progress = False


def _any_processing(images) -> bool:
    """S5/D-5: file-moving _AI ops refuse only while an image is *processing*
    — a live run idles between passes, so a run-state guard would never re-open."""
    return any(getattr(img, "status", "") == "processing" for img in images)


def run_folder_ai_request(bridge, mode: str) -> str:
    """Disk _AI op guards + submit; refuses mid-job/mid-scan. Pending JSON."""
    if _any_processing(bridge.state.images):
        return json.dumps({"ok": False, "error": "stop the run first"})
    if getattr(bridge, "_scan_in_progress", False):
        return json.dumps({"ok": False, "pending": True, "error": "scan already in progress"})
    root_path, err = resolve_scan_root(bridge.state.folder)
    if err:
        return json.dumps({"ok": False, "error": err})
    try:
        bridge._scan_in_progress = True
        bridge._log(f"Folder {'Only _AI' if mode == 'only' else 'Drop _AI'} in {root_path}...", "warn")
        folder_ai_service.submit_folder_ai(
            bridge, root_path,
            set(bridge.state.folder.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"])), mode)
    except Exception as e:
        bridge._scan_in_progress = False
        return json.dumps({"ok": False, "error": str(e)})
    return json.dumps({"ok": True, "pending": True})


def copy_path_text(bridge, path_str: str) -> str:
    """Copy path: Qt first, subprocess chain fallback. Result JSON."""
    try:
        ok, warn = clipboard_copy(path_str)
        if ok:
            bridge._log(f"📋 Copied to clipboard: {path_str}", "info")
            return json.dumps({"ok": True, "path": path_str, "method": "qt"})
        if warn:
            bridge._log(warn, "warn")
        res = file_service.copy_text_to_clipboard(path_str, log=bridge._log)
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e), "path": path_str})


def generate_thumb_result(path: Path, img_id: str) -> dict:
    """Thumbnail dict for one file (service does pixels; we tag the id)."""
    res = generate_thumbnail_data_url(path, size=96, quality=80)
    res["id"] = img_id
    return res


def thumb_job_done(bridge, img_id: str, fut) -> None:
    """Cache finished thumbnail + emit ready; always releases the slot."""
    try:
        res = fut.result()
        if res.get("ok") and res.get("data_url"):
            bridge._thumb_cache[img_id] = res["data_url"]
            try:
                payload = json.dumps(res, ensure_ascii=False)
                bridge.thumbnail_ready.emit(img_id, payload)
            except Exception:
                pass
        bridge._thumb_in_progress.discard(img_id)
    except Exception:
        bridge._thumb_in_progress.discard(img_id)


def start_thumb_job(bridge, img_id: str, path: Path) -> str:
    """Generate off-thread (pending JSON) or sync; caches data URLs."""
    if bridge._thumb_executor:
        bridge._thumb_in_progress.add(img_id)
        try:
            fut = bridge._thumb_executor.submit(generate_thumb_result, path, img_id)
            fut.add_done_callback(functools.partial(thumb_job_done, bridge, img_id))
        except Exception:
            bridge._thumb_in_progress.discard(img_id)
            res = generate_thumb_result(path, img_id)
            if res.get("ok") and res.get("data_url"):
                bridge._thumb_cache[img_id] = res["data_url"]
            return json.dumps(res, ensure_ascii=False)
        return json.dumps({"ok": False, "pending": True, "id": img_id,
                           "fallback_url": f"file://{path}"}, ensure_ascii=False)
    res = generate_thumb_result(path, img_id)
    if res.get("ok") and res.get("data_url"):
        bridge._thumb_cache[img_id] = res["data_url"]
    return json.dumps(res, ensure_ascii=False)


def request_thumbnail(bridge, img_id: str) -> str:
    """Cached data URL, pending ticket, or error JSON (never blocks)."""
    try:
        if img_id in bridge._thumb_cache:
            cached = bridge._thumb_cache[img_id]
            return json.dumps({"ok": True, "id": img_id, "data_url": cached, "cached": True},
                              ensure_ascii=False)
        target = find_image(bridge.state.images, img_id)
        if not target:
            return json.dumps({"ok": False, "error": "not found"})
        p = Path(target.absolute_path)
        if not p.exists():
            return json.dumps({"ok": False, "error": "file not exists"})
        if img_id in bridge._thumb_in_progress:
            return json.dumps({"ok": False, "pending": True, "id": img_id,
                               "fallback_url": f"file://{p}"}, ensure_ascii=False)
        return start_thumb_job(bridge, img_id, p)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


class QueueScanMixin(FolderPickMixin):
    """Image queue, folder scan, queue file tools, folder-AI slots."""

    @Slot(str, result=str)
    def get_image_thumbnail(self, img_id: str):
        """Base64 thumbnail — cache/pending, never blocks the UI thread."""
        return request_thumbnail(self, img_id)

    @Slot(str, result=str)
    def reveal_in_explorer(self, path_str: str):
        """Open file in Explorer/Finder (not a link)."""
        return json.dumps(file_service.reveal_path(path_str, log=self._log))

    @Slot(str, result=str)
    def copy_path_to_clipboard(self, path_str: str):
        """Copy file path to clipboard — Qt first, subprocess fallback."""
        return copy_path_text(self, path_str)

    @Slot(result=str)
    def scan_folder(self):
        """Non-blocking scan to avoid UI freeze on mouse clicks."""
        if getattr(self, "_scan_in_progress", False):
            return json.dumps({"ok": False, "pending": True, "error": "scan already in progress"})
        root_path, err = resolve_scan_root(self.state.folder)
        if err:
            return json.dumps({"ok": False, "error": err})
        try:
            self._scan_in_progress = True
            self._log(f"🔍 Scanning folder {root_path}… (non-blocking)", "info")
            run_off_ui_thread(self, run_scan_merge, root_path)
            return json.dumps({"ok": True, "pending": True, "count": 0,
                               "message": "scan started non-blocking"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def scan_folder_new_batch(self):
        """Clear queue then scan — non-blocking to avoid freeze."""
        try:
            cleared = clear_queue_images(self)
            self._log(f"🗑 Cleared {cleared} old — scanning new batch non-blocking", "warn")
            root_path, err = resolve_scan_root(self.state.folder)
            if err:
                return json.dumps({"ok": False, "error": err, "cleared": cleared})
            self._scan_in_progress = True
            run_off_ui_thread(self, run_scan_new_batch, root_path, cleared)
            return json.dumps({"ok": True, "pending": True, "cleared": cleared,
                               "message": "new batch scan started non-blocking"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, bool, result=str)
    def set_image_selected(self, img_id: str, selected: bool):
        img = find_image(self.state.images, img_id)
        if img is None:
            return json.dumps({"ok": False, "error": "not found"})
        img.selected = bool(selected)
        if selected and img.status == "skipped":
            img.status = "pending"
        feed.commit_queue(self, "set_selected")
        return json.dumps({"ok": True})

    @Slot(bool, str, result=str)
    def bulk_select(self, selected: bool, filter_status: str):
        count = apply_bulk_selection(self.state.images, bool(selected), filter_status)
        feed.commit_queue(self, "bulk_select")
        return json.dumps({"ok": True, "count": count})

    @Slot(result=str)
    def clear_images(self):
        # compat alias of run_control's clear_queue (log packing table)
        return self.clear_queue()

    @Slot(result=str)
    def drop_ai_suffix(self):
        """Drop _AI: strip the suffix from filenames in the picker folder."""
        return run_folder_ai_request(self, "strip")

    @Slot(result=str)
    def keep_only_ai_files(self):
        """Only _AI: delete non-_AI images in the picker folder."""
        return run_folder_ai_request(self, "only")

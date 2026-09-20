"""Run control panel — queue retry/reset, run lifecycle, job-action events.

ideal-size(reason): 10-slot run surface plus gate/phase splits — start_run
and cancel_current each exceed 20 LOC as one function, so gate checks and
cancel phases live beside their single callers per RULE 16; splitting the
file would scatter slot+phase pairs. Emits JobAction events for the runner
(F8: panel func takes 2 params, bridge keeps the seam). Reuses
single-source queue_scan/url_queue funcs via acyclic sibling imports.
"""

import json
import logging
from datetime import datetime

from app.core.run_scope import run_scope
from app.services.batch_orchestrator import run_batch
from app.services.run_state import batch_active, schedule_coro
from app.ui.panels.queue_scan import push_queue_undo
from app.ui.panels.url_queue import _URL_GATE_MSG, _urls_gate_error, enabled_urls
from app.ui.qt_compat import Slot

log = logging.getLogger("arena")


def revive_failed_images(images) -> int:
    """Requeue failed images (pending + selected); returns revived count."""
    count = 0
    for img in images:
        if img.status == "failed":
            img.status = "pending"
            img.selected = True
            img.error = None
            count += 1
    return count


def clear_image_state(bridge) -> int:
    """Drop all images/jobs (undo already pushed); returns removed count."""
    count = len(bridge.state.images)
    bridge.state.images = []
    bridge.state.jobs = []
    bridge.state.recalculate_progress()
    bridge._save_arena()
    return count


def reset_image_state(img, selected: bool) -> None:
    """Return one image to pending (run-scope selection as given)."""
    img.status = "pending"
    img.selected = selected
    img.error = None
    img.output_path = None
    img.assigned_url_id = None
    img.attempt_count = 0


def check_start_inputs(bridge):
    """Prompt/selection/URL gates; error JSON when blocked, else None."""
    prompt = bridge.state.prompt.get("user_prompt", "").strip()
    if not prompt:
        bridge._log("⚠ Prompt is empty — set prompt before running", "warn")
        return json.dumps({"ok": False, "error": "empty prompt"})
    if not run_scope(bridge.state.images):
        bridge._log("⚠ No selected images — select images in queue", "warn")
        return json.dumps({"ok": False, "error": "no selected images"})
    gate = _urls_gate_error(bridge, enabled_urls(bridge.state.urls))
    if gate:
        msg, level = _URL_GATE_MSG[gate]
        bridge._log(msg, level)
        return json.dumps({"ok": False, "error": gate})
    return None


def check_start_ready(bridge):
    """CDP/run-state gates; error JSON when blocked, else None."""
    if not bridge.cdp or not bridge.cdp.is_connected:
        bridge._log("❌ Chrome not connected — click Diagnose, Refresh, Connect first. CDP must be connected to automate.", "error")
        return json.dumps({"ok": False, "error": "cdp not connected"})
    if bridge._run_state == "running":
        bridge._log("⚠ Already running", "warn")
        return json.dumps({"ok": False, "error": "already running"})
    if batch_active(bridge):
        bridge._log("⚠ A batch is still active (paused / stopping / unwinding) — Resume or Cancel it first", "warn")
        return json.dumps({"ok": False, "error": "batch still active"})
    return None


def cancel_batch_future(bridge) -> None:
    """Cancel the running batch future immediately (best effort)."""
    try:
        if bridge._batch_future:
            bridge._batch_future.cancel()
            bridge._log("✖ Batch future cancelled", "warn")
    except Exception as e:
        bridge._log(f"Cancel future failed: {e}", "warn")


def fail_processing_images(bridge) -> None:
    """Fail run-scope processing images (cancel sweep, best effort)."""
    try:
        # Also emit job_finished cancelled for current jobs
        from app.core.enums import ImageStatus
        for img in run_scope(bridge.state.images):
            if img.status == ImageStatus.PROCESSING.value:
                img.status = ImageStatus.FAILED.value
                img.error = "Cancelled by user"
        bridge.state.recalculate_progress()
        bridge._save_arena()
    except Exception:
        pass


def describe_action_block(block):
    """(block_id, block_name, color, highlight_ms) for any block shape."""
    if isinstance(block, str):
        return block, block, "#FF0000", 2000
    block_id = getattr(block, 'id', '') or getattr(block, 'block_id', '') or str(block)
    block_name = getattr(block, 'display_name', None) or getattr(block, 'name', block_id)
    if callable(block_name):
        block_name = block_name()
    return block_id, block_name, getattr(block, 'color', '#FF0000'), getattr(block, 'highlight_duration_ms', 2000)


def emit_action_highlight(bridge, action, desc) -> None:
    """Overlay the action rect for running/success steps (best effort)."""
    _, block_name, color, highlight_ms = desc
    if not (action.rect and action.status in ("running", "success")):
        return
    try:
        hr = {
            "x": action.rect.get("x", 0),
            "y": action.rect.get("y", 0),
            "width": action.rect.get("width", 100),
            "height": action.rect.get("height", 100),
            "duration": highlight_ms / 1000 if highlight_ms else 2,
            "label": block_name,
            "color": color,
        }
        bridge.highlight_rect.emit(json.dumps(hr))
    except Exception:
        pass


def emit_job_action_status(bridge, action) -> None:
    """JobAction event → job_action_status (+ highlight overlay)."""
    try:
        block_id, block_name, color, highlight_ms = describe_action_block(action.block)
        payload = json.dumps({
            "job_id": action.job_id,
            "block_id": block_id,
            "block_name": block_name,
            "status": action.status,
            "message": action.message,
            "rect": action.rect,
            "color": color,
            "highlight_duration_ms": highlight_ms,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }, ensure_ascii=False)
        bridge.job_action_status.emit(action.job_id, block_id, payload)
        emit_action_highlight(bridge, action, (block_id, block_name, color, highlight_ms))
    except Exception as e:
        log.warning(f"emit job action status failed: {e}")


class RunControlMixin:
    """Run-control slots: queue retry/reset, run lifecycle."""

    @Slot(result=str)
    def retry_failed(self):
        count = revive_failed_images(self.state.images)
        self.state.recalculate_progress()
        self._save_arena()
        push_queue_undo(self)
        return json.dumps({"ok": True, "count": count})

    @Slot(result=str)
    def clear_queue(self):
        """Clear entire image queue — start new batch. User requested: should able to start new batch not adding only."""
        try:
            # push undo before clearing so user can undo
            try:
                push_queue_undo(self)
            except Exception:
                pass
            count = clear_image_state(self)
            self._log(f"🗑 Cleared image queue: {count} images removed — ready for new batch", "warn")
            return json.dumps({"ok": True, "count": count})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def reset_all(self):
        for img in self.state.images:
            reset_image_state(img, False)
        self.state.jobs = []
        self.state.recalculate_progress()
        self._save_arena()
        push_queue_undo(self)
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
                push_queue_undo(self)
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(str, result=str)
    def reset_image(self, img_id: str):
        for img in self.state.images:
            if img.id == img_id:
                reset_image_state(img, False)
                self.state.recalculate_progress()
                self._save_arena()
                push_queue_undo(self)
                return json.dumps({"ok": True})
        return json.dumps({"ok": False, "error": "not found"})

    @Slot(result=str)
    def start_run(self):
        err = check_start_inputs(self) or check_start_ready(self)
        if err:
            return err
        prompt = self.state.prompt.get("user_prompt", "").strip()
        selected = run_scope(self.state.images)
        urls = enabled_urls(self.state.urls)
        self._run_state = "running"
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._log(f"🚀 Run started: {len(selected)} images, {len(urls)} urls, prompt len {len(prompt)}", "success")
        self._emit_arena_state()
        fut = schedule_coro(self, run_batch(self))
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
        cancel_batch_future(self)
        fail_processing_images(self)
        return json.dumps({"ok": True})

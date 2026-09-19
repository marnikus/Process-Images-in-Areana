"""Goldens for Bridge._do_run_batch (roadmap W1.1) — the safety net for
the W1.3–W1.5 bridge decomposition.

RULE 8: each golden runs the REAL, UNMODIFIED ``_do_run_batch`` against
the shared doubles (``bridge_doubles``) and asserts the observable trace
(block statuses, signals, run-state). Any refactor must keep these green
byte-for-byte.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import bridge_doubles as bd
from app.core.action_blocks import default_stack
from app.core.enums import ImageStatus


def run_batch(bridge: "bd.RecordingBridge") -> list:
    from app.ui.bridge import Bridge

    asyncio.run(Bridge._do_run_batch(bridge))
    return bridge.trace


def patch_ctrl(monkeypatch, bridge):
    # patch BOTH the cdp_arena export and the orchestrator's module-level
    # import — the batch pipeline may enter through either
    monkeypatch.setattr("app.browser.cdp_arena.CDPArenaController", bridge.make_ctrl)
    monkeypatch.setattr("app.services.batch_orchestrator.CDPArenaController", bridge.make_ctrl)


@pytest.fixture
def no_sleep(monkeypatch):
    """Collapse the pipeline's real-time sleeps (3s pre-download, reload
    pauses) so the goldens run in milliseconds; behaviour under test is
    the event/trace order, not wall-clock time."""
    import asyncio as _asyncio

    async def _fast_sleep(_seconds, *args, **kwargs):
        return None

    monkeypatch.setattr(_asyncio, "sleep", _fast_sleep)


@pytest.fixture
def one_image(tmp_path: Path):
    src = tmp_path / "pic.png"
    src.write_bytes(b"\x89PNG-fake-source-bytes")
    return bd.make_image(src)


HAPPY_SCRIPT = {
    "is_page_ready": (True, []),
    "capture_baseline": {"output_count": 0, "output_srcs": [], "spinning": False},
    "is_security_dialog_visible": False,
    "attach_image": (True, "attached"),
    "insert_prompt": (True, ""),
    "verify_prompt": (True, ""),
    "submit": (True, ""),
    "is_generating": False,
    # (status, payload) — the real controller's "completed" contract
    "wait_for_new_output": lambda ctrl, *a, **kw: bd.completed_wait_result(
        kw.get("correlation_id") or (a[1] if len(a) > 1 else "J") or "J"),
    "is_generating": (False, {}),
    # (ok, file_bytes, content_type) — real 3-tuple; >100 bytes or the
    # pipeline treats it as an error page and keeps waiting
    "download_image": (True, b"\x89PNG-downloaded-" * 10, "image/png"),
    "reload_page": (True, "reloaded"),
    "get_generation_state": {"spinning": False, "state": "idle"},
}


def test_golden_happy_path(no_sleep, monkeypatch, one_image):
    """One image, full default stack, every ctrl step succeeds."""
    bridge = bd.RecordingBridge(images=[one_image], ctrl_script=dict(HAPPY_SCRIPT))
    patch_ctrl(monkeypatch, bridge)
    trace = run_batch(bridge)

    actions = [e for e in bd.action_trace(trace) if e[0] == "action"]
    # every enabled block of the default stack reaches a terminal status, in order
    terminal = [a for a in actions if a[2] in ("success", "skipped", "failed")]
    enabled = [b.block_id for b in default_stack() if b.enabled]
    assert [a[1] for a in terminal] == enabled, terminal
    assert all(a[2] in ("success", "skipped") for a in terminal), terminal
    # the image lifecycle is observable end-to-end
    assert ("signal", "job_started") in [t[:2] for t in bd.action_trace(trace)]
    assert ("signal", "job_finished") in [t[:2] for t in bd.action_trace(trace)]
    assert one_image.status == ImageStatus.COMPLETED.value
    assert bridge._run_state == "idle"


def test_golden_mid_fail_stops_image_and_marks_failed(no_sleep, monkeypatch, one_image):
    """A failing INSERT_PROMPT aborts the image; the batch reports and idles."""
    script = dict(HAPPY_SCRIPT)
    script["insert_prompt"] = (False, "prompt box not found")
    bridge = bd.RecordingBridge(images=[one_image], ctrl_script=script)
    patch_ctrl(monkeypatch, bridge)
    trace = run_batch(bridge)

    actions = bd.action_trace(trace)
    statuses = {(a[1], a[2]) for a in actions if a[0] == "action"}
    assert ("INSERT_PROMPT", "failed") in statuses
    # nothing after INSERT_PROMPT runs for this image
    started = [a[1] for a in actions if a[0] == "action" and a[2] == "running"]
    assert "HIGHLIGHT_SUBMIT" not in started
    assert "SUBMIT" not in started
    assert "WAIT_OUTPUT" not in started
    assert one_image.status == ImageStatus.FAILED.value
    assert one_image.error is not None
    assert bridge._run_state == "idle"


def test_golden_captcha_pause_then_resume(no_sleep, monkeypatch, one_image):
    """CHECK_SECURITY sees a dialog: run pauses, settles, resumes, completes."""
    script = dict(HAPPY_SCRIPT)
    seen = {"n": 0}

    def security(ctrl, *a, **kw):
        seen["n"] += 1
        # visible only during the CHECK_SECURITY block itself
        # (later calls happen inside the generation wait loops)
        return seen["n"] == 1

    script["is_security_dialog_visible"] = security
    bridge = bd.RecordingBridge(images=[one_image], ctrl_script=script)
    patch_ctrl(monkeypatch, bridge)
    trace = run_batch(bridge)

    actions = bd.action_trace(trace)
    statuses = [(a[1], a[2]) for a in actions if a[0] == "action"]
    assert ("CHECK_SECURITY", "running") in statuses  # solving/waiting notice
    assert ("CHECK_SECURITY", "success") in statuses
    # pause -> resume state transitions are observable
    states = [e[1] for e in trace if e[0] == "state"]
    assert "paused" in states and "running" in states
    # the run completes after the pause (captcha settled)
    assert ("signal", "job_started") in [t[:2] for t in actions]
    assert ("signal", "job_finished") in [t[:2] for t in actions]
    assert one_image.status == ImageStatus.COMPLETED.value


# ---- W1.5 insurance goldens: signal-heavy uncovered paths ------------------

def test_golden_wait_download_retries_then_succeeds(no_sleep, monkeypatch, one_image):
    """WAIT_OUTPUT's verification download fails small once (still
    generating), a second wait returns the real output, then DOWNLOAD's
    first attempt succeeds — exercising the retry/extend-cycle paths."""
    calls = {"wait": 0, "download": 0}

    def wait(ctrl, *a, **kw):
        calls["wait"] += 1
        cid = kw.get("correlation_id") or "J"
        if calls["wait"] == 1:
            return ("completed", {**bd.completed_wait_result(cid)[1],
                                  "new_src": "https://r2/early.png"})
        return bd.completed_wait_result(cid, src="https://r2/final.png")

    def download(ctrl, src, *a, **kw):
        calls["download"] += 1
        if calls["download"] == 1:
            return (True, b"tiny", "image/png")  # < 100 bytes: not ready
        return (True, b"\x89PNG-good-" * 20, "image/png")

    script = dict(HAPPY_SCRIPT)
    script["wait_for_new_output"] = wait
    script["download_image"] = download
    script["is_generating"] = (True, {"spinning": True})
    bridge = bd.RecordingBridge(images=[one_image], ctrl_script=script)
    patch_ctrl(monkeypatch, bridge)
    trace = run_batch(bridge)

    assert calls["wait"] >= 2 and calls["download"] >= 2
    assert one_image.status == ImageStatus.COMPLETED.value
    statuses = [(a[1], a[2]) for a in bd.action_trace(trace) if a[0] == "action"]
    # extend-cycle notice lands on the first wait-type block (AWAIT runs first)
    assert ("AWAIT_PROCESSING_IMAGE", "waiting") in statuses or ("WAIT_OUTPUT", "waiting") in statuses
    assert ("SAVE", "success") in statuses


def test_golden_download_retries_after_reload(no_sleep, monkeypatch, one_image):
    """WAIT succeeds with a small download already stored is NOT the case
    here: wait returns completed with no usable bytes, so the DOWNLOAD
    block runs its attempt/reload cycles and finally succeeds."""
    calls = {"download": 0, "reload": 0}

    def download(ctrl, src, *a, **kw):
        calls["download"] += 1
        if calls["download"] <= 2:
            return (True, b"tiny", "image/png")  # too small twice
        return (True, b"\x89PNG-late-" * 20, "image/png")

    script = dict(HAPPY_SCRIPT)
    script["download_image"] = download
    script["is_generating"] = (False, {})
    script["reload_page"] = lambda ctrl, *a, **kw: calls.__getitem__("reload") or calls.update(reload=calls["reload"] + 1) or (True, "reloaded")
    bridge = bd.RecordingBridge(images=[one_image], ctrl_script=script)
    patch_ctrl(monkeypatch, bridge)
    trace = run_batch(bridge)

    assert calls["download"] >= 3
    assert one_image.status == ImageStatus.COMPLETED.value
    statuses = [(a[1], a[2]) for a in bd.action_trace(trace) if a[0] == "action"]
    assert ("DOWNLOAD", "success") in statuses
    assert ("ADVANCE", "success") in statuses

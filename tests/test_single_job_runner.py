"""single_job_runner tests (roadmap W1.4).

Covers the full-block handler map — including the 7 handlers ported from
the bridge inline loop (HIGHLIGHT_*, VERIFY_ATTACHMENT, VERIFY_PROMPT,
PAUSE, TYPE_PROMPT) — plus the run_blocks_for_image pipeline, using the
SHARED doubles from tests/characterization/bridge_doubles.py (one
harness, per the worst-first design).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "characterization"))
import bridge_doubles as bd  # noqa: E402

from app.core.action_blocks import default_stack
from app.services.single_job_runner import (
    JobCtx,
    _handle_highlight,
    _handle_pause,
    _handle_type_prompt,
    _handle_verify_attachment,
    _handle_verify_prompt,
    _handler_map,
    run_blocks_for_image,
)


def make_ctx(bridge, ctrl, tmp_path, stack=None, final_prompt="p [JOB-ID]"):
    src = tmp_path / "pic.png"
    src.write_bytes(b"x" * 20)
    img = bd.make_image(src)
    bridge._stack = stack if stack is not None else default_stack()
    return JobCtx(
        bridge=bridge, ctrl=ctrl, client=bridge.cdp, tab_id="tab-1", img=img,
        urls=bridge._get_enabled_urls(), job_id="J1", corr_id="J1",
        final_prompt=final_prompt,
    )


def happy_script():
    return {
        "is_page_ready": (True, []),
        "capture_baseline": {"output_count": 0, "output_srcs": [], "spinning": False},
        "is_security_dialog_visible": False,
        "attach_image": (True, "attached"),
        "insert_prompt": (True, ""),
        "verify_prompt": (True, ""),
        "submit": (True, ""),
        "wait_for_new_output": lambda ctrl, *a, **kw: bd.completed_wait_result(kw.get("correlation_id") or "J1"),
        "is_generating": (False, {}),
        "download_image": (True, b"\x89PNG-downloaded-" * 10, "image/png"),
        "reload_page": (True, "reloaded"),
        "get_generation_state": {"spinning": False, "state": "idle"},
    }


def make_bridge(tmp_path, script):
    src = tmp_path / "pic.png"
    src.write_bytes(b"x" * 20)
    images = [bd.make_image(src)]
    return bd.RecordingBridge(images=images, ctrl_script=script)


# ---- handler map completeness (W1.4 exit) ---------------------------------

def test_handler_map_covers_every_default_block():
    hmap = _handler_map()
    missing = [b.block_id for b in default_stack() if b.enabled and b.block_id not in hmap]
    assert not missing, f"blocks without runner handler: {missing}"


# ---- pipeline --------------------------------------------------------------

@pytest.mark.unit
def test_pipeline_happy_path(tmp_path, monkeypatch):
    async def _fast_sleep(_s, *a, **kw):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    bridge = make_bridge(tmp_path, happy_script())
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    failed, error, new_src, file_bytes = asyncio.run(run_blocks_for_image(ctx))
    assert failed is False and error == ""
    assert new_src == "https://r2/out.png"
    assert file_bytes and len(file_bytes) > 100
    statuses = [e for e in bridge.trace if e[0] == "action"]
    assert all(s[2] in ("success", "skipped", "running") for s in statuses), statuses
    assert ("ADVANCE", "success") in [(s[1], s[2]) for s in statuses]


@pytest.mark.unit
def test_pipeline_mid_fail_required_stops(tmp_path):
    script = happy_script()
    script["insert_prompt"] = (False, "box missing")
    bridge = make_bridge(tmp_path, script)
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    failed, error, new_src, file_bytes = asyncio.run(run_blocks_for_image(ctx))
    assert failed is True
    assert "Prompt failed" in error
    # nothing from SUBMIT onward runs (INSERT_PROMPT is required -> break);
    # new_src may be set by the earlier AWAIT block — that is characterized
    started = [s[1] for s in bridge.trace if s[0] == "action" and s[2] == "running"]
    assert "SUBMIT" not in started
    assert "SAVE" not in started
    assert "ADVANCE" not in started


@pytest.mark.unit
def test_pipeline_cancel_before_first_block(tmp_path):
    bridge = make_bridge(tmp_path, happy_script())
    bridge._cancel_requested = True
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    failed, error, _, _ = asyncio.run(run_blocks_for_image(ctx))
    assert failed is True
    assert error in ("Cancelled", "Aborted by operator")
    assert bridge.trace == [] or all(e[0] != "action" or e[2] != "success"
                                     for e in bridge.trace)


@pytest.mark.unit
def test_pipeline_disabled_blocks_skipped(tmp_path):
    stack = default_stack()
    for b in stack:
        b.enabled = (b.block_id == "INSERT_PROMPT")
    bridge = make_bridge(tmp_path, happy_script())
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path, stack=stack)
    failed, error, _, _ = asyncio.run(run_blocks_for_image(ctx))
    assert failed is False
    statuses = [(s[1], s[2]) for s in bridge.trace if s[0] == "action"]
    assert statuses == [("INSERT_PROMPT", "running"), ("INSERT_PROMPT", "success")]


# ---- ported handlers (direct units) ----------------------------------------

@pytest.mark.unit
def test_highlight_handler_success_and_skip(tmp_path):
    async def run(bridge, ctrl):
        blocks = [b for b in default_stack() if b.block_id.startswith("HIGHLIGHT")]
        for b in blocks:
            await _handle_highlight(make_ctx(bridge, ctrl, tmp_path), b)
    bridge = make_bridge(tmp_path, {"highlight_selector": (True, None)})
    asyncio.run(run(bridge, bridge.make_ctrl(bridge.cdp)))
    emitted = [e for e in bridge.trace if e[0] == "action"]
    assert len(emitted) == 3 and all(e[2] == "success" for e in emitted)

    bridge2 = make_bridge(tmp_path, {"highlight_selector": RuntimeError("boom")})
    asyncio.run(run(bridge2, bridge2.make_ctrl(bridge2.cdp)))
    emitted2 = [e for e in bridge2.trace if e[0] == "action"]
    assert all(e[2] == "success" for e in emitted2)  # highlight never fails hard


@pytest.mark.unit
def test_verify_attachment_found_and_not_found(tmp_path):
    bridge = make_bridge(tmp_path, {})
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)
    block = next(b for b in default_stack() if b.block_id == "VERIFY_ATTACHMENT")
    asyncio.run(_handle_verify_attachment(ctx, block))  # FakeCDP probe: found
    emitted = [e for e in bridge.trace if e[0] == "action"]
    assert emitted[-1] == ("action", "VERIFY_ATTACHMENT", "success")

    bridge2 = make_bridge(tmp_path, {})
    bridge2.cdp = bd.FakeCDP(probe_result={"found": False, "total": 0})
    ctx2 = make_ctx(bridge2, bridge2.make_ctrl(bridge2.cdp), tmp_path)
    with pytest.raises(RuntimeError, match="Verify attachment failed"):
        asyncio.run(_handle_verify_attachment(ctx2, block))


@pytest.mark.unit
def test_verify_prompt_retries_once_then_fails(tmp_path):
    calls = {"verify": 0, "insert": 0}

    def verify(ctrl, *a, **kw):
        calls["verify"] += 1
        return (False, "mismatch") if calls["verify"] < 3 else (True, "ok")

    def insert(ctrl, *a, **kw):
        calls["insert"] += 1
        return (True, "reinserted")

    script = {"verify_prompt": verify, "insert_prompt": insert}
    bridge = make_bridge(tmp_path, script)
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)
    block = next(b for b in default_stack() if b.block_id == "VERIFY_PROMPT")
    with pytest.raises(RuntimeError, match="Prompt verification failed"):
        asyncio.run(_handle_verify_prompt(ctx, block))
    assert calls == {"verify": 2, "insert": 1}  # one retry, then hard fail


@pytest.mark.unit
def test_pause_handler_sleeps_extra_duration(tmp_path, monkeypatch):
    slept = []

    async def fake_sleep(sec, *a, **kw):
        slept.append(sec)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    bridge = make_bridge(tmp_path, {})
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)

    class Block:
        block_id, display_name = "PAUSE", "Pause"
        extra = {"duration_ms": 1500}
    asyncio.run(_handle_pause(ctx, Block()))
    assert slept == [1.5]
    assert bridge.trace[-1] == ("action", "PAUSE", "success")


@pytest.mark.unit
def test_type_prompt_handler(tmp_path):
    bridge = make_bridge(tmp_path, {"insert_prompt": (True, "typed")})
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)

    class Block:
        block_id, display_name = "TYPE_PROMPT", "Type"
        selector, color, highlight_ms = "", "#fff", 10
        highlight_enabled = True
        extra = {"typing_speed_ms": 5}
    asyncio.run(_handle_type_prompt(ctx, Block()))
    assert bridge.trace[-1] == ("action", "TYPE_PROMPT", "success")

    bridge2 = make_bridge(tmp_path, {"insert_prompt": (False, "gone")})
    ctx2 = make_ctx(bridge2, bridge2.make_ctrl(bridge2.cdp), tmp_path)
    with pytest.raises(RuntimeError, match="Type prompt failed"):
        asyncio.run(_handle_type_prompt(ctx2, Block()))


# ---- edge/exception paths (W1.4 coverage) ----------------------------------

class FakePool:
    def __init__(self):
        self.marks = []

    def mark_waiting(self, tab, kind):
        self.marks.append(("waiting", tab, kind))

    def mark_busy(self, tab, job):
        self.marks.append(("busy", tab, job))


@pytest.mark.unit
def test_pool_marked_waiting_and_busy_during_wait(tmp_path, monkeypatch):
    async def _fast_sleep(_s, *a, **kw):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    pool = FakePool()
    bridge = make_bridge(tmp_path, happy_script())
    bridge._page_pool = pool
    bridge._ensure_page_pool = lambda: pool
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    failed, error, src, fbytes = asyncio.run(run_blocks_for_image(ctx))
    assert failed is False
    assert ("waiting", "tab-1", "generation") in pool.marks
    assert ("busy", "tab-1", "J1") in pool.marks


@pytest.mark.unit
def test_ctrl_exceptions_surface_as_failed_reasons(tmp_path):
    def boom(ctrl, *a, **kw):
        raise RuntimeError("ctrl exploded")
    script = happy_script()
    script["attach_image"] = boom
    script["insert_prompt"] = boom
    script["capture_baseline"] = boom
    bridge = make_bridge(tmp_path, script)
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    failed, error, _, _ = asyncio.run(run_blocks_for_image(ctx))
    assert failed is True
    assert "Attach failed" in error  # ATTACH is required -> first hard stop


@pytest.mark.unit
def test_submit_falls_back_to_visual_click(tmp_path):
    script = happy_script()
    script["submit"] = (False, "no ctrl submit")
    bridge = make_bridge(tmp_path, script)
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    from app.services.single_job_runner import submit_job
    block = next(b for b in default_stack() if b.block_id == "SUBMIT")
    ok, reason = asyncio.run(submit_job(ctx, block))
    assert ok is True  # FakeCDP probe -> find_and_click succeeds


@pytest.mark.unit
def test_wait_not_completed_returns_error(tmp_path, monkeypatch):
    async def _fast_sleep(_s, *a, **kw):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    script = happy_script()
    script["wait_for_new_output"] = lambda ctrl, *a, **kw: ("failed", {"error": "Timeout after 5ms"})
    bridge = make_bridge(tmp_path, script)
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    failed, error, src, fbytes = asyncio.run(run_blocks_for_image(ctx))
    assert failed is True
    assert "Wait failed" in error


@pytest.mark.unit
def test_wait_small_download_treated_as_not_downloadable(tmp_path, monkeypatch):
    async def _fast_sleep(_s, *a, **kw):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    script = happy_script()
    script["download_image"] = (True, b"tiny", "image/png")  # < 100 bytes
    bridge = make_bridge(tmp_path, script)
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    from app.services.single_job_runner import wait_for_output
    src, fbytes, err = asyncio.run(wait_for_output(ctx, 1000))
    assert src == "https://r2/out.png"
    assert fbytes is None
    assert err == "not downloadable"


@pytest.mark.unit
def test_download_block_requires_new_src(tmp_path, monkeypatch):
    async def _fast_sleep(_s, *a, **kw):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)
    from app.services.single_job_runner import _handle_download
    bridge = make_bridge(tmp_path, happy_script())
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    block = next(b for b in default_stack() if b.block_id == "DOWNLOAD")
    with pytest.raises(RuntimeError, match="No new_src"):
        asyncio.run(_handle_download(ctx, block))


@pytest.mark.unit
def test_validate_and_save_require_bytes(tmp_path):
    from app.services.single_job_runner import _handle_save, _handle_validate
    bridge = make_bridge(tmp_path, happy_script())
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)
    block = next(b for b in default_stack() if b.block_id == "VALIDATE")
    with pytest.raises(RuntimeError, match="No bytes"):
        asyncio.run(_handle_validate(ctx, block))
    save_block = next(b for b in default_stack() if b.block_id == "SAVE")
    with pytest.raises(RuntimeError, match="No bytes to save"):
        asyncio.run(_handle_save(ctx, save_block))


@pytest.mark.unit
def test_captcha_outcome_branches(tmp_path):
    from types import SimpleNamespace
    from app.services.single_job_runner import _handle_captcha_outcome
    bridge = make_bridge(tmp_path, happy_script())
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)
    with pytest.raises(RuntimeError, match="Cancelled during CAPTCHA"):
        _handle_captcha_outcome(ctx, SimpleNamespace(status="stopped"))
    with pytest.raises(RuntimeError, match="boom"):  # page_error uses outcome.reason
        _handle_captcha_outcome(ctx, SimpleNamespace(status="page_error", reason="boom"))
    with pytest.raises(RuntimeError, match="Page error during CAPTCHA"):  # reason empty -> default
        _handle_captcha_outcome(ctx, SimpleNamespace(status="page_error", reason=None))
    _handle_captcha_outcome(ctx, SimpleNamespace(status="token_stale"))  # logged, no raise
    assert any(e[0] == "log" and "token stale" in e[2] for e in bridge.trace)
    _handle_captcha_outcome(ctx, SimpleNamespace(status="ok"))


@pytest.mark.unit
def test_security_dialog_visible_settles_via_captcha_module(tmp_path):
    """Visible dialog goes through handle_captcha (RULE 20 choke point)."""
    script = happy_script()
    seen = {"n": 0}

    def security(ctrl, *a, **kw):
        seen["n"] += 1
        return seen["n"] == 1  # visible once, then cleared (settles fast)
    script["is_security_dialog_visible"] = security
    bridge = make_bridge(tmp_path, script)
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    from app.services.single_job_runner import check_security
    settled = asyncio.run(check_security(ctx))
    assert settled is True


@pytest.mark.unit
def test_captcha_job_lines_drained_once(tmp_path):
    from app.services.single_job_runner import _emit_captcha_job_lines
    bridge = make_bridge(tmp_path, happy_script())
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    ctrl._captcha_reports = [{"eid": "E1", "source": "check-security"}]
    _emit_captcha_job_lines(ctx, False, "")
    lines = [e[2] for e in bridge.trace if e[0] == "log" and "CAPTCHA_JOB" in e[2]]
    assert len(lines) == 1 and "E1" in lines[0]
    assert ctrl._captcha_reports == []  # drained


@pytest.mark.unit
def test_custom_find_uses_find_and_click(tmp_path):
    from app.services.single_job_runner import _handle_custom
    bridge = make_bridge(tmp_path, happy_script())
    ctx = make_ctx(bridge, bridge.make_ctrl(bridge.cdp), tmp_path)
    block = next(b for b in default_stack() if b.block_id == "CUSTOM_FIND" or b.block_id == "ADVANCE")
    # CUSTOM_FIND may not be in the default stack; craft one
    if getattr(block, "block_id", "") != "CUSTOM_FIND":

        class CFBlock:
            block_id, display_name, name = "CUSTOM_FIND", "Find", "Find"
            selector, label_selector, match_text, match_mode = "button", "", "", "contains"
            click_enabled, click_selector = True, ""
            highlight_enabled, confirm_pause_ms = True, 1
            highlight_ms, highlight_duration_ms = 1, 1
            fallback_selector, fallback_text, color = "", "", "#fff"
            enabled, required = True, False
        block = CFBlock()
    asyncio.run(_handle_custom(ctx, block))
    assert bridge.trace[-1][0] == "action"


@pytest.mark.unit
def test_maybe_delay_awaits_pre_delay():
    from app.services.single_job_runner import _maybe_delay

    class B:
        pre_delay_ms = 50
    asyncio.run(_maybe_delay(B()))


@pytest.mark.unit
def test_cancel_mid_loop_stops_after_failure(tmp_path):
    script = happy_script()
    script["insert_prompt"] = (False, "nope")
    bridge = make_bridge(tmp_path, script)
    bridge._cancel_requested = False

    class ToggleBridge(type(bridge)):
        pass
    ctrl = bridge.make_ctrl(bridge.cdp)
    ctx = make_ctx(bridge, ctrl, tmp_path)
    # flip cancel on after first block runs
    orig = bridge._get_action_blocks

    def flip():
        bridge._cancel_requested = True
        return orig()
    bridge._get_action_blocks = flip
    failed, error, _, _ = asyncio.run(run_blocks_for_image(ctx))
    assert failed is True

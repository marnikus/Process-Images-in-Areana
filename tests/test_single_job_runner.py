"""Converged block handlers (A2): each ported handler incl. fail paths.

RULE 8: real handler functions + real ActionBlocks; only CDP/bridge faked.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import single_job_runner as sjr
from tests.characterization.harness import make_block


def make_bridge(stack=None, pool=None, cancel=False):
    events = []
    logs = []
    state = SimpleNamespace(
        settings=SimpleNamespace(
            timeouts={"generation": 180},
            output={"suffix": "_AI", "overwrite": False,
                    "preserve_format": True,
                    "unique_suffix_template": "{base}_AI_{n}{ext}"}))
    return SimpleNamespace(
        _cancel_requested=cancel,
        _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: d),
        state=state,
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_job_action_status=lambda action: events.append(
            (getattr(action.block, "block_id", action.block), action.status, action.message)),
        _emit_pool_status=lambda: logs.append(("pool", "")),
        _get_action_blocks=lambda: list(stack or []),
        highlight_rect=SimpleNamespace(emit=lambda p: logs.append(("rect", p))),
        _events=events,
        _logs=logs,
    )


def make_ctrl(**kw):
    async def _ok(*a, **k):
        return True, "ok"

    async def _visible():
        return False

    async def _highlight(sel, **k):
        return {"x": 1, "y": 2, "width": 3, "height": 4}

    async def _wait(*a, **k):
        return "completed", {"new_src": "https://x/new.png"}

    async def _dl(src):
        return True, b"z" * 200, "image/png"

    async def _overlay(*a, **k):
        return True

    base = dict(attach_image=_ok, insert_prompt=_ok, submit=_ok,
                verify_prompt=_ok, is_security_dialog_visible=_visible,
                highlight_selector=_highlight, wait_for_new_output=_wait,
                download_image=_dl, show_watcher_overlay=_overlay,
                hide_watcher_overlay=_overlay, capture_baseline=None)
    base.update(kw)
    if base["capture_baseline"] is None:
        async def _base():
            return {"output_count": 0, "output_srcs": []}
        base["capture_baseline"] = _base
    return SimpleNamespace(**base)


def make_client(found=True, rect=None):
    async def _eval(js):
        return json.dumps({"found": found,
                           "rect": rect or {"x": 1, "y": 1, "width": 5, "height": 5}})
    return SimpleNamespace(evaluate=_eval)


def make_img(tmp_path):
    p = tmp_path / "in.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 120)
    return SimpleNamespace(absolute_path=str(p), relative_path="in.png",
                           status="pending", output_path=None, error=None)


def make_ctx(bridge, ctrl, client, img, tab_id="t1"):
    return sjr.JobCtx(bridge=bridge, ctrl=ctrl, client=client, tab_id=tab_id,
                      img=img, urls=[], job_id="j1", corr_id="c1",
                      final_prompt="p [JOB-ID: c1]",
                      baseline={"output_count": 0, "output_srcs": []})


def instant_sleep(monkeypatch):
    async def _fast(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast)


def test_handler_map_covers_all_types():
    from tests.characterization.harness import FULL_STACK
    hmap = sjr._handler_map()
    assert len(hmap) == 20
    for bid in FULL_STACK:
        assert bid in hmap, bid


@pytest.mark.asyncio
async def test_highlight_found_and_missing(tmp_path):
    for found in (True, False):
        bridge = make_bridge()
        ctx = make_ctx(bridge, make_ctrl(), make_client(found), make_img(tmp_path))
        blk = make_block("HIGHLIGHT", selector="div.main")
        if found:
            await sjr._handle_highlight(ctx, blk)
            assert bridge._events[-1][1] == "success"
        else:
            with pytest.raises(RuntimeError, match="not found"):
                await sjr._handle_highlight(ctx, blk)


@pytest.mark.asyncio
async def test_pause_uses_extra_duration(tmp_path):
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    await sjr._handle_pause(ctx, make_block("PAUSE", extra={"duration_ms": 5}))
    assert bridge._events[-1] == ("PAUSE", "success", "Paused 5ms")


@pytest.mark.asyncio
async def test_type_prompt_ok_and_fail(tmp_path):
    async def _fail(prompt):
        return False, "nope"
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    await sjr._handle_type_prompt(ctx, make_block("TYPE_PROMPT"))
    assert bridge._events[-1][1] == "success"
    ctx2 = make_ctx(bridge, make_ctrl(insert_prompt=_fail), make_client(),
                    make_img(tmp_path))
    with pytest.raises(RuntimeError, match="Type prompt failed"):
        await sjr._handle_type_prompt(ctx2, make_block("TYPE_PROMPT"))


def test_marker_selector_defaults():
    assert sjr._marker_selector(make_block("HIGHLIGHT_ATTACH")) == 'input[type="file"]'
    assert sjr._marker_selector(make_block("HIGHLIGHT_PROMPT")) == 'textarea[name="message"]'
    assert "Send message" in sjr._marker_selector(make_block("HIGHLIGHT_SUBMIT"))
    assert sjr._marker_selector(make_block("HIGHLIGHT_SUBMIT", selector="b.c")) == "b.c"


@pytest.mark.asyncio
async def test_marker_never_fails(tmp_path, monkeypatch):
    async def _boom(sel, **k):
        raise RuntimeError("cdp gone")
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(highlight_selector=_boom), make_client(),
                   make_img(tmp_path))
    await sjr._handle_marker_highlight(ctx, make_block("HIGHLIGHT_SUBMIT"))
    assert bridge._events[-1][1] == "success"


@pytest.mark.asyncio
async def test_verify_attachment_found_and_missing(tmp_path):
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(True), make_img(tmp_path))
    await sjr._handle_verify_attachment(ctx, make_block("VERIFY_ATTACHMENT"))
    assert bridge._events[-1][1] == "success"
    ctx2 = make_ctx(bridge, make_ctrl(), make_client(False), make_img(tmp_path))
    with pytest.raises(RuntimeError, match="preview not found"):
        await sjr._handle_verify_attachment(ctx2, make_block("VERIFY_ATTACHMENT"))


@pytest.mark.asyncio
async def test_verify_prompt_ok_retry_ok_retry_fail(tmp_path):
    async def _mismatch(expected):
        return False, "Mismatch"

    async def _match(expected):
        return True, "Exact match"

    states = iter([False, True])
    async def _flaky(expected):
        return (False, "Mismatch") if next(states) is False else (True, "ok")

    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(verify_prompt=_match), make_client(),
                   make_img(tmp_path))
    await sjr._handle_verify_prompt(ctx, make_block("VERIFY_PROMPT"))
    assert bridge._events[-1][1] == "success"

    ctx2 = make_ctx(bridge, make_ctrl(verify_prompt=_flaky), make_client(),
                    make_img(tmp_path))
    await sjr._handle_verify_prompt(ctx2, make_block("VERIFY_PROMPT"))
    assert bridge._events[-1][1] == "success"

    ctx3 = make_ctx(bridge, make_ctrl(verify_prompt=_mismatch), make_client(),
                    make_img(tmp_path))
    with pytest.raises(RuntimeError, match="Prompt verification failed"):
        await sjr._handle_verify_prompt(ctx3, make_block("VERIFY_PROMPT"))


def _clicks_by_script(monkeypatch, script):
    calls = []

    async def fake(client, req, engine=None):
        calls.append(req.selector)
        for key, res in script.items():
            if key in req.selector:
                return res
        return "ok"

    monkeypatch.setattr(sjr, "find_and_click", fake)
    return calls


@pytest.mark.asyncio
async def test_custom_fallback_wins(tmp_path, monkeypatch):
    _clicks_by_script(monkeypatch, {"missing": "fail"})
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    blk = make_block("CUSTOM_FIND", selector="button#missing",
                     fallback_selector="button#fallback")
    await sjr._handle_custom(ctx, blk)
    assert bridge._events[-1][1] == "success"


@pytest.mark.asyncio
async def test_custom_all_fail_raises(tmp_path, monkeypatch):
    _clicks_by_script(monkeypatch, {"button": "fail"})
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    with pytest.raises(RuntimeError, match="fallbacks"):
        await sjr._handle_custom(
            ctx, make_block("CUSTOM_FIND", selector="button#a",
                            fallback_selector="button#b"))
    with pytest.raises(RuntimeError, match="Find & Click failed for button#a$"):
        await sjr._handle_custom(ctx, make_block("CUSTOM_FIND", selector="button#a"))


@pytest.mark.asyncio
async def test_submit_visual_fallback_controller_order(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    submitted = []

    async def _submit():
        submitted.append(1)
        return True, "Clicked"

    # visual ok -> controller untouched
    _clicks_by_script(monkeypatch, {})
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(submit=_submit), make_client(), make_img(tmp_path))
    ok, reason = await sjr.submit_job(ctx, make_block("SUBMIT", selector="button.send"))
    assert ok and not submitted and reason.startswith("Clicked")

    # visual fail -> fallback wins, controller untouched
    _clicks_by_script(monkeypatch, {"send": "fail"})
    ctx = make_ctx(bridge, make_ctrl(submit=_submit), make_client(), make_img(tmp_path))
    ok, reason = await sjr.submit_job(
        ctx, make_block("SUBMIT", selector="button.send", fallback_selector="button.fb"))
    assert ok and not submitted and "fallback" in reason

    # all visual fail -> controller last resort
    _clicks_by_script(monkeypatch, {"button": "fail"})
    ctx = make_ctx(bridge, make_ctrl(submit=_submit), make_client(), make_img(tmp_path))
    ok, reason = await sjr.submit_job(ctx, make_block("SUBMIT", selector="button.send"))
    assert ok and submitted and "controller" in reason


@pytest.mark.asyncio
async def test_submit_total_failure_raises(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    _clicks_by_script(monkeypatch, {"button": "fail"})

    async def _dead():
        return False, "disabled"

    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(submit=_dead), make_client(), make_img(tmp_path))
    ok, _ = await sjr.submit_job(ctx, make_block("SUBMIT", selector="button.send"))
    assert not ok
    with pytest.raises(RuntimeError, match="Submit failed"):
        await sjr._handle_submit(ctx, make_block("SUBMIT", selector="button.send"))


@pytest.mark.asyncio
async def test_disabled_and_unknown_skip(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    stack = [make_block("OBSERVE_BASELINE", enabled=False),
             make_block("NOPE_CUSTOM")]
    bridge = make_bridge(stack)
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    failed, _err, _s, _b = await sjr.run_blocks_for_image(ctx)
    assert not failed
    kinds = {(b, s) for b, s, _m in bridge._events}
    assert ("OBSERVE_BASELINE", "skipped") in kinds
    assert ("NOPE_CUSTOM", "skipped") in kinds


@pytest.mark.asyncio
async def test_validate_ext_pil_fallback_tiny(tmp_path):
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buf, format="PNG")
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    ctx.file_bytes = buf.getvalue()
    ctx.new_src = "https://x/new.jpg"
    await sjr._handle_validate(ctx, make_block("VALIDATE"))
    assert ctx.ext == ".png"  # real bytes win over src suffix

    ctx.file_bytes = b"junk" * 100
    ctx.new_src = "https://x/new.webp"
    await sjr._handle_validate(ctx, make_block("VALIDATE"))
    assert ctx.ext == ".webp"

    ctx.file_bytes = b"tiny"
    with pytest.raises(RuntimeError, match="Validation failed"):
        await sjr._handle_validate(ctx, make_block("VALIDATE"))


@pytest.mark.asyncio
async def test_save_uses_ctx_ext(tmp_path):
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    ctx.file_bytes = b"z" * 200
    ctx.ext = ".webp"
    out = await sjr.save_image(ctx, ctx.file_bytes)
    assert out is not None and out.suffix == ".webp" and out.exists()


@pytest.mark.asyncio
async def test_attach_open_dialog_click(tmp_path, monkeypatch):
    calls = _clicks_by_script(monkeypatch, {})
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    blk = make_block("ATTACH_IMAGE", click_selector="button.open", click_enabled=True)
    await sjr._handle_attach(ctx, blk)
    assert calls == ["button.open"]
    assert bridge._events[-1][1] == "success"
    calls.clear()
    await sjr._handle_attach(ctx, make_block("ATTACH_IMAGE", click_selector=""))
    assert calls == []


@pytest.mark.asyncio
async def test_mark_waiting_busy_use_pool_attr():
    marked = []

    class Pool:
        def mark_waiting(self, tab, kind):
            marked.append(("waiting", tab, kind))

        def mark_busy(self, tab, job):
            marked.append(("busy", tab, job))

    bridge = make_bridge(pool=Pool())
    ctx = make_ctx(bridge, make_ctrl(), make_client(), SimpleNamespace())
    sjr._mark_waiting(ctx, "generation")
    sjr._mark_busy(ctx)
    assert marked == [("waiting", "t1", "generation"), ("busy", "t1", "j1")]
    bare = make_bridge(pool=None)
    delattr(bare, "_page_pool")
    ctx2 = make_ctx(bare, make_ctrl(), make_client(), SimpleNamespace())
    sjr._mark_waiting(ctx2, "x")  # no pool attr -> silent no-op
    sjr._mark_busy(ctx2)


@pytest.mark.asyncio
async def test_wait_announces_watching_state(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    await sjr._handle_wait(ctx, make_block("WAIT_OUTPUT", timeout_ms=1000))
    assert bridge._events[0][1] == "running"
    bridge2 = make_bridge()
    ctx2 = make_ctx(bridge2, make_ctrl(), make_client(), make_img(tmp_path))
    await sjr._handle_wait(ctx2, make_block("AWAIT_PROCESSING_IMAGE", timeout_ms=1000))
    assert bridge2._events[0][1] == "waiting"


@pytest.mark.asyncio
async def test_security_block_reports_watcher_ownership(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    import app.services.captcha as cap_mod

    async def unexpected_solver(_ctx):
        raise AssertionError("image pipeline must not solve CAPTCHA")

    monkeypatch.setattr(cap_mod, "handle_captcha", unexpected_solver)
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    await sjr._handle_security(ctx, make_block("CHECK_SECURITY"))
    assert bridge._events == [("CHECK_SECURITY", "success", "CAPTCHA delegated to Watcher")]


@pytest.mark.asyncio
async def test_cancel_error_text_matches_legacy(tmp_path):
    bridge = make_bridge(cancel=True)
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    failed, err, stop = await sjr._run_one_checked(ctx, make_block("SUBMIT"))
    assert (failed, err, stop) == (True, "Cancelled by user", True)


@pytest.mark.asyncio
async def test_wait_for_output_timeout_and_unfinished_paths(tmp_path):
    async def _timeout(*a, **k):
        return "timeout", {"error": "timed out"}

    async def _unfinished(*a, **k):
        return "uploading", {"new_src": "https://x/part.png"}

    for script, want in [(_timeout, (None, None, "timed out")),
                         (_unfinished, ("https://x/part.png", None, "not downloadable"))]:
        ctx = make_ctx(make_bridge(), make_ctrl(wait_for_new_output=script),
                       make_client(), make_img(tmp_path))
        assert await sjr.wait_for_output(ctx, 1000) == want


@pytest.mark.asyncio
async def test_security_does_not_settle_or_mutate_captcha_policy(tmp_path, monkeypatch):
    import app.services.captcha as cap_mod

    async def unexpected_solver(_ctx):
        raise AssertionError("image pipeline must not solve CAPTCHA")

    monkeypatch.setattr(cap_mod, "handle_captcha", unexpected_solver)
    ctrl = make_ctrl()
    ctrl._resume_policy = SimpleNamespace(settled_at=None)
    ctx = make_ctx(make_bridge(), ctrl, make_client(), make_img(tmp_path))
    assert await sjr.check_security(ctx) is False
    assert ctrl._resume_policy.settled_at is None


@pytest.mark.asyncio
async def test_security_does_not_create_solver_stop_closure(tmp_path, monkeypatch):
    import app.services.captcha as cap_mod

    async def unexpected_solver(_ctx):
        raise AssertionError("image pipeline must not solve CAPTCHA")

    monkeypatch.setattr(cap_mod, "handle_captcha", unexpected_solver)
    for cancel in (False, True):
        ctx = make_ctx(make_bridge(cancel=cancel), make_ctrl(),
                       make_client(), make_img(tmp_path))
        assert await sjr.check_security(ctx) is False

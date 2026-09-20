"""B8 — a downloaded image is never lost to a later block failure.

Field case (bugfix-verification.md §B8): DOWNLOAD delivered 940 KB, then a
user-added "Find & Click" block failed (page context gone for a second) and
the job ended failed without saving the bytes. Policy now: once the output is
secured, a later non-output block failure is a warning; the stack continues
so VALIDATE/SAVE keep the image. VALIDATE/SAVE failures and cancellation keep
their legacy semantics.

B9 extension (§B9): a NON-REQUIRED block that failed BEFORE the download no
longer fails a job whose image was then downloaded, validated and saved —
field case: VERIFY_ATTACHMENT "preview not found" (a broken probe) marked
every job failed although the image sat on disk. Required breaks, VALIDATE/
SAVE failures and cancellation are never forgiven (goldens req_fail/cancel).

RULE 8: real runner, real ActionBlocks; only CDP/bridge/click runner faked.
"""

from __future__ import annotations

import pytest

from app.services import single_job_runner as sjr
from tests.characterization.harness import make_block
from tests.test_single_job_runner import (instant_sleep, make_bridge, make_client,
                                          make_ctrl, make_ctx, make_img)

pytestmark = pytest.mark.unit

CORE = ["OBSERVE_BASELINE", "CHECK_SECURITY", "ATTACH_IMAGE", "INSERT_PROMPT",
        "SUBMIT", "WAIT_OUTPUT", "DOWNLOAD"]
TAIL = ["VALIDATE", "SAVE", "ADVANCE"]


def _fail_clicks(monkeypatch, failing_substr="button"):
    calls = []

    async def fake(client, req, engine=None):
        calls.append(req.selector)
        return "fail" if failing_substr in req.selector else "ok"
    monkeypatch.setattr(sjr, "find_and_click", fake)
    return calls


def _warnings(bridge):
    return [m for m, lvl in bridge._logs if lvl == "warn" and "continuing so the image is saved" in m]


async def _run(tmp_path, monkeypatch, stack):
    instant_sleep(monkeypatch)
    _fail_clicks(monkeypatch)
    bridge = make_bridge(stack)
    img = make_img(tmp_path)
    ctx = make_ctx(bridge, make_ctrl(), make_client(), img)
    failed, err, _src, data = await sjr.run_blocks_for_image(ctx)
    return bridge, img, failed, err, data


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [False, True])
async def test_post_download_custom_failure_keeps_image_and_completes(tmp_path, monkeypatch, required):
    stack = [make_block(b) for b in CORE]
    stack.append(make_block("CUSTOM_FIND", selector="button", required=required))
    stack += [make_block(b) for b in TAIL]
    bridge, img, failed, err, data = await _run(tmp_path, monkeypatch, stack)
    assert failed is False and err == ""
    assert img.output_path and img.status == "completed"
    assert data and len(data) >= 100
    events = {(b, s) for b, s, _m in bridge._events}
    assert ("CUSTOM_FIND", "failed") in events  # the block itself still shows red
    assert ("SAVE", "success") in events and ("ADVANCE", "success") in events
    warns = _warnings(bridge)
    assert len(warns) == 1 and "Find & Click failed for button" in warns[0]


def _soft_warnings(bridge):
    return [m for m, lvl in bridge._logs if lvl == "warn" and "Completed with warnings" in m]


def _pre_download_optional_stack(block):
    stack = [make_block(b) for b in CORE[:5]]
    stack.append(block)  # before WAIT/DOWNLOAD
    stack += [make_block(b) for b in CORE[5:] + TAIL]
    return stack


@pytest.mark.asyncio
async def test_pre_download_optional_failure_completes_once_the_image_is_saved(tmp_path, monkeypatch):
    stack = _pre_download_optional_stack(make_block("CUSTOM_FIND", selector="button"))
    bridge, img, failed, err, data = await _run(tmp_path, monkeypatch, stack)
    assert failed is False and err == ""                 # B9: saved image → completed
    assert img.output_path and img.status == "completed"
    events = {(b, s) for b, s, _m in bridge._events}
    assert ("CUSTOM_FIND", "failed") in events            # the block row still shows red
    assert _warnings(bridge) == []                        # the B8 line is post-download only
    warns = _soft_warnings(bridge)
    assert len(warns) == 1 and "Find & Click failed for button" in warns[0]


@pytest.mark.asyncio
async def test_pre_download_optional_failure_stays_failed_when_nothing_was_saved(tmp_path, monkeypatch):
    stack = _pre_download_optional_stack(make_block("CUSTOM_FIND", selector="button"))
    stack = [b for b in stack if b.block_id != "SAVE"]
    bridge, img, failed, err, _data = await _run(tmp_path, monkeypatch, stack)
    assert failed is True and "Find & Click failed for button" in err
    assert not img.output_path and _soft_warnings(bridge) == []


@pytest.mark.asyncio
async def test_pre_download_required_failure_still_breaks_and_fails(tmp_path, monkeypatch):
    stack = _pre_download_optional_stack(make_block("CUSTOM_FIND", selector="button", required=True))
    bridge, img, failed, err, _data = await _run(tmp_path, monkeypatch, stack)
    assert failed is True and "Find & Click failed for button" in err
    assert not img.output_path
    ran = [b for b, s, _m in bridge._events if s == "running"]
    assert "WAIT_OUTPUT" not in ran and _soft_warnings(bridge) == []


@pytest.mark.asyncio
async def test_verify_attachment_not_found_is_a_warning_when_the_image_is_saved(tmp_path, monkeypatch):
    """The §B9 field case: VERIFY_ATTACHMENT reported 'preview not found' and
    the job ended failed although DOWNLOAD/SAVE had delivered the image."""
    instant_sleep(monkeypatch)
    stack = _pre_download_optional_stack(make_block("VERIFY_ATTACHMENT"))
    bridge = make_bridge(stack)
    img = make_img(tmp_path)
    ctx = make_ctx(bridge, make_ctrl(), make_client(found=False), img)
    failed, err, _src, data = await sjr.run_blocks_for_image(ctx)
    assert failed is False and err == ""
    assert img.output_path and img.status == "completed" and data
    msgs = [m for b, s, m in bridge._events if b == "VERIFY_ATTACHMENT" and s == "failed"]
    assert msgs == ["Verify attachment failed: preview not found div.flex.flex-wrap.gap-2 img"]
    warns = _soft_warnings(bridge)
    assert len(warns) == 1 and "preview not found" in warns[0]


@pytest.mark.asyncio
async def test_verify_attachment_found_reports_the_rect(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    stack = _pre_download_optional_stack(make_block("VERIFY_ATTACHMENT"))
    bridge = make_bridge(stack)
    ctx = make_ctx(bridge, make_ctrl(), make_client(found=True), make_img(tmp_path))
    failed, err, _src, _data = await sjr.run_blocks_for_image(ctx)
    assert failed is False and err == ""
    ok = [(s, m) for b, s, m in bridge._events if b == "VERIFY_ATTACHMENT" and s != "running"]
    assert ok == [("success", "Attachment preview found div.flex.flex-wrap.gap-2 img")]
    assert _soft_warnings(bridge) == []


@pytest.mark.asyncio
async def test_two_optional_failures_are_both_listed_in_the_warning(tmp_path, monkeypatch):
    stack = [make_block(b) for b in CORE[:5]]
    stack += [make_block("CUSTOM_FIND", selector="button.a"), make_block("CUSTOM_FIND", selector="button.b")]
    stack += [make_block(b) for b in CORE[5:] + TAIL]
    bridge, img, failed, err, _data = await _run(tmp_path, monkeypatch, stack)
    assert failed is False and img.output_path
    warns = _soft_warnings(bridge)
    assert len(warns) == 1 and "button.a" in warns[0] and "button.b" in warns[0]


@pytest.mark.asyncio
async def test_save_failure_after_download_still_fails_the_job(tmp_path, monkeypatch):
    async def _no_save(ctx, data):
        return None
    monkeypatch.setattr(sjr, "save_image", _no_save)
    stack = [make_block(b) for b in CORE + TAIL]
    bridge, img, failed, err, _data = await _run(tmp_path, monkeypatch, stack)
    assert failed is True and err == "Save failed"
    assert not img.output_path and _warnings(bridge) == []


@pytest.mark.asyncio
async def test_validate_failure_after_download_still_fails_the_job(tmp_path, monkeypatch):
    async def _bad_validate(ctx, block):
        raise RuntimeError("Validation failed: corrupt")
    monkeypatch.setattr(sjr, "_handle_validate", _bad_validate)  # _handler_map reads globals at call time
    stack = [make_block(b) for b in CORE + TAIL]
    bridge, img, failed, err, _data = await _run(tmp_path, monkeypatch, stack)
    assert failed is True and "Validation failed" in err
    assert _warnings(bridge) == []


@pytest.mark.asyncio
async def test_cancelled_post_download_failure_is_not_downgraded(tmp_path, monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge(cancel=True)
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    ctx.file_bytes = b"z" * 200
    blk = make_block("CUSTOM_FIND", selector="button")
    assert sjr._post_download_warning(ctx, blk, "boom", secured=True) is False
    assert sjr._post_download_warning(ctx, make_block("SAVE"), "boom", secured=True) is False


def test_output_secured_threshold(tmp_path):
    bridge = make_bridge()
    ctx = make_ctx(bridge, make_ctrl(), make_client(), make_img(tmp_path))
    assert sjr._output_secured(ctx) is False
    ctx.file_bytes = b"z" * 100
    assert sjr._output_secured(ctx) is False  # same >100 rule as DOWNLOAD itself
    ctx.file_bytes = b"z" * 101
    assert sjr._output_secured(ctx) is True

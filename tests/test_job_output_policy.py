"""B8 — a downloaded image is never lost to a later block failure.

Field case (bugfix-verification.md §B8): DOWNLOAD delivered 940 KB, then a
user-added "Find & Click" block failed (page context gone for a second) and
the job ended failed without saving the bytes. Policy now: once the output is
secured, a later non-output block failure is a warning; the stack continues
so VALIDATE/SAVE keep the image. VALIDATE/SAVE failures, pre-download
failures and cancellation keep their legacy semantics (goldens unchanged).

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


@pytest.mark.asyncio
async def test_pre_download_optional_failure_keeps_legacy_failed_status(tmp_path, monkeypatch):
    stack = [make_block(b) for b in CORE[:5]]
    stack.append(make_block("CUSTOM_FIND", selector="button"))  # before WAIT/DOWNLOAD
    stack += [make_block(b) for b in CORE[5:] + TAIL]
    bridge, img, failed, err, data = await _run(tmp_path, monkeypatch, stack)
    assert failed is True and "Find & Click failed for button" in err
    assert img.output_path  # legacy: non-required → stack continued and saved
    assert _warnings(bridge) == []  # the B8 warning is post-download only


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

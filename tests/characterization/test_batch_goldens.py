"""Batch characterization goldens (A1): 12 scenarios pin legacy behavior.

Each test runs the SAME scenario through every registered runner
(A1: legacy loop; A4: orchestrator) and compares the structural trace
against the golden. UPDATE_GOLDENS=1 regenerates after review.
"""

import pytest

from .fakes import install_patches
from .harness import (CORE_STACK, FULL_STACK, RUNNERS, arm_hooks, assert_markers,
                      build_bridge, build_stack, check_golden, collect_trace,
                      make_block, normalize)


async def _run(env):
    for name, runner in RUNNERS.items():
        await runner(env)


def _trace(env, patched):
    return collect_trace(env, patched.clicks)


@pytest.mark.integration
async def test_happy_full_stack(tmp_path, monkeypatch):
    stack = build_stack(
        FULL_STACK,
        ATTACH_IMAGE={"click_selector": "button.open", "click_enabled": True},
        CUSTOM_FIND={"selector": "button#go", "fallback_selector": ""},
    )
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, stack, n_images=1)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("happy_full", trace)
    assert_markers(trace, ["Starting", "Job completed", "Batch complete"])


@pytest.mark.integration
async def test_happy_two_images(tmp_path, monkeypatch):
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("happy_two", trace)
    assert_markers(trace, ["Batch complete"])


@pytest.mark.integration
async def test_disabled_blocks_skipped(tmp_path, monkeypatch):
    stack = build_stack(
        FULL_STACK,
        HIGHLIGHT_ATTACH={"enabled": False},
        VERIFY_PROMPT={"enabled": False},
        AWAIT_PROCESSING_IMAGE={"enabled": False},
    )
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, stack, n_images=1)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("disabled", trace)
    skipped = [b for b, s in trace["events"] if s == "skipped"]
    assert "HIGHLIGHT_ATTACH" in skipped and "VERIFY_PROMPT" in skipped


@pytest.mark.integration
async def test_nonrequired_midfail_continues(tmp_path, monkeypatch):
    ids = ["OBSERVE_BASELINE", "CHECK_SECURITY", "ATTACH_IMAGE",
           "INSERT_PROMPT", "VERIFY_PROMPT", "SUBMIT", "WAIT_OUTPUT",
           "DOWNLOAD", "VALIDATE", "SAVE", "ADVANCE"]
    patched = install_patches(monkeypatch, ctrl_script={"verify_prompt_ok": False})
    env = build_bridge(tmp_path, build_stack(ids), n_images=1)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("nonreq_fail", trace)
    assert trace["images"][0]["status"] == "failed"


@pytest.mark.integration
async def test_required_midfail_breaks_job(tmp_path, monkeypatch):
    patched = install_patches(
        monkeypatch, ctrl_script={"fail": {"attach_image": "nope"},
                                  "fail_times": {"attach_image": 1}})
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("req_fail", trace)
    assert trace["images"][0]["status"] == "failed"
    assert trace["images"][1]["status"] == "completed"


@pytest.mark.integration
async def test_cancel_before_next_block(tmp_path, monkeypatch):
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    arm_hooks(env, after_event={
        ("SUBMIT", "success"): lambda e: setattr(e.bridge, "_cancel_requested", True),
    })
    await _run(env)
    trace = _trace(env, patched)
    check_golden("cancel", trace)
    assert trace["images"][0]["status"] == "failed"
    assert trace["images"][0]["error"] == "Cancelled by user"


@pytest.mark.integration
async def test_stop_after_current(tmp_path, monkeypatch):
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2)
    arm_hooks(env, after_finish=lambda e: setattr(e.bridge, "_stop_after", True))
    await _run(env)
    trace = _trace(env, patched)
    check_golden("stop_after", trace)
    assert trace["images"][0]["status"] == "completed"
    assert trace["images"][1]["status"] == "pending"


@pytest.mark.integration
async def test_captcha_pause_resume(tmp_path, monkeypatch):
    patched = install_patches(monkeypatch, ctrl_script={"visible_times": 2},
                              captcha_status="solved")
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("captcha", trace)
    assert patched.captcha.calls == ["check-security"]
    assert trace["images"][0]["status"] == "completed"


@pytest.mark.integration
async def test_tab_abort_fails_job(tmp_path, monkeypatch):
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo
    from app.services.cooldown_service import request_tab_abort

    patched = install_patches(monkeypatch)
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="tab1", ws_url="ws://x", title="Arena",
                           url="https://arena.ai/chat"))
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, pool=pool)
    arm_hooks(env, after_event={
        ("ATTACH_IMAGE", "success"): lambda e: request_tab_abort(e.bridge._page_pool, "tab1"),
    })
    await _run(env)
    trace = _trace(env, patched)
    check_golden("abort", trace)
    assert trace["images"][0]["error"] == "Aborted by operator"


@pytest.mark.integration
async def test_unknown_block_skipped(tmp_path, monkeypatch):
    ids = ["OBSERVE_BASELINE", "NOPE_CUSTOM", "ATTACH_IMAGE", "INSERT_PROMPT",
           "SUBMIT", "WAIT_OUTPUT", "DOWNLOAD", "VALIDATE", "SAVE", "ADVANCE"]
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(ids), n_images=1)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("unknown", trace)
    assert ["NOPE_CUSTOM", "skipped"] in trace["events"]
    assert trace["images"][0]["status"] == "completed"


@pytest.mark.integration
async def test_custom_find_fallback(tmp_path, monkeypatch):
    patched = install_patches(monkeypatch,
                              click_script={"button#missing": "fail"})
    custom = make_block("CUSTOM_FIND", selector="button#missing",
                        fallback_selector="button#fallback", fallback_text="")
    stack = [custom] + build_stack(CORE_STACK)
    env = build_bridge(tmp_path, stack, n_images=1)
    await _run(env)
    trace = _trace(env, patched)
    check_golden("custom_fallback", trace)
    assert trace["clicks"][0] == "button#missing"
    assert "button#fallback" in trace["clicks"]


@pytest.mark.integration
async def test_no_usable_tab(tmp_path, monkeypatch):
    from .fakes import FakeCDP

    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1,
                       cdp=FakeCDP(tab_id=""))
    await _run(env)
    trace = _trace(env, patched)
    check_golden("no_tab", trace)
    assert trace["events"] == []
    assert trace["run_state"] == "idle"


# ---- harness unit tests (RULE 8: helpers fail if broken) ----

def test_normalize_strips_corr_ids():
    trace = {"logs": ["[20260919-120000-A7F3] Starting x"], "events": []}
    assert normalize(trace)["logs"] == ["[JOBID] Starting x"]


def test_check_golden_roundtrip_and_drift(tmp_path, monkeypatch):
    import json
    import tests.characterization.harness as h

    monkeypatch.delenv("UPDATE_GOLDENS", raising=False)
    monkeypatch.setattr(h, "GOLDENS", tmp_path)
    h.check_golden("rt", {"events": [["A", "success"]], "logs": ["zzz"]})
    saved = json.loads((tmp_path / "rt.json").read_text())
    assert saved == {"events": [["A", "success"]]}  # logs excluded
    h.check_golden("rt", {"events": [["A", "success"]], "logs": ["other"]})
    with pytest.raises(AssertionError):
        h.check_golden("rt", {"events": [["A", "failed"]], "logs": []})
    assert (tmp_path / "rt.json").exists()

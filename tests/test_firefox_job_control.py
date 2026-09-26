"""The Firefox image job under control: pause / cancel, manual security, the
lane reset seam and odd failures (design D-1 §16/§18, 2026-09-25; split from
test_firefox_job.py by the 2026-09-26 refactor, R6)."""

import asyncio
import json

import pytest

from app.core.enums import ImageStatus, JobStatus
from app.services import firefox_job as fj
from app.services.firefox_job_journal import journal_of
from tests.firefox_job_harness import (
    PROMPT, Bridge, attached, baseline, happy_site, observed, prompt_ok, record, run, sent,
)

pytestmark = pytest.mark.unit


# ── pause / cancel (§16) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_before_submit_sends_nothing(tmp_path, monkeypatch):
    bridge = Bridge(tmp_path / "cfg")

    def attach_then_cancel(token):
        bridge._cancel_requested = True
        return attached()(token)

    site = happy_site(PROMPT, attach=attach_then_cancel)
    verdict, _, _, resets = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict == fj.Verdict(True, "Cancelled") and "submit" not in site.calls
    assert record(bridge) is None and "nothing was sent" in bridge.text()


@pytest.mark.asyncio
async def test_cancel_after_submit_keeps_evidence_and_skips_new_chat(tmp_path, monkeypatch):
    bridge = Bridge(tmp_path / "cfg")

    def submit_then_cancel(token):
        bridge._cancel_requested = True
        return sent()

    site = happy_site(PROMPT, submit=submit_then_cancel)
    verdict, _, _, resets = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict == fj.Verdict(True, fj.CANCEL_REVIEW, True)
    assert record(bridge)["status"] == JobStatus.NEEDS_REVIEW.value
    assert await resets[0]() == (True, "skipped (needs review)") and "reset" not in site.calls


@pytest.mark.asyncio
async def test_task_cancel_mid_submit_lets_the_macro_finish_then_reviews(tmp_path, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_submit(token):
        started.set()
        await release.wait()
        return sent()

    from tests.firefox_job_harness import TAB, firefox_pool, image, source_image, wire
    site = happy_site(PROMPT, submit=slow_submit)
    wire(monkeypatch, site)
    img = image(source_image(tmp_path))
    bridge = Bridge(tmp_path / "cfg", [img])
    task = asyncio.ensure_future(fj.run_job(fj.JobStart(bridge, firefox_pool(), TAB, img, "c1", PROMPT), []))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()                      # the send macro is never abandoned
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert img.status == ImageStatus.NEEDS_REVIEW.value and img.error == fj.CANCEL_REVIEW


@pytest.mark.asyncio
async def test_pause_holds_before_submit_then_reverifies_and_continues(tmp_path, monkeypatch):
    from app.services.firefox_job_phases import prompt_text, sha_of
    monkeypatch.setattr(fj, "PAUSE_POLL_S", 0.01)
    bridge = Bridge(tmp_path / "cfg")

    def prompt_then_pause(token):
        bridge._pause_requested = True
        asyncio.get_running_loop().call_later(0.05, setattr, bridge, "_pause_requested", False)
        return prompt_ok(PROMPT)

    verify = observed(found=False, composer_sha=sha_of(prompt_text(PROMPT)))

    def recheck(token):
        reply = verify(token)
        reply["observe"]["previews"] = [{"alt": f"arena_{token}.png"}]
        return reply

    site = happy_site(PROMPT, prompt=prompt_then_pause, observe=[recheck, observed()])
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict.failed is False
    assert site.calls == ["baseline", "attach", "prompt", "observe", "submit", "observe"]
    assert "paused before submit at prompt_verified" in bridge.text() and "re-verified" in bridge.text()


@pytest.mark.asyncio
async def test_page_changed_during_pause_fails_safely_unsent(tmp_path, monkeypatch):
    monkeypatch.setattr(fj, "PAUSE_POLL_S", 0.01)
    bridge = Bridge(tmp_path / "cfg")

    def prompt_then_pause(token):
        bridge._pause_requested = True
        asyncio.get_running_loop().call_later(0.03, setattr, bridge, "_pause_requested", False)
        return prompt_ok(PROMPT)

    site = happy_site(PROMPT, prompt=prompt_then_pause,
                      observe=observed(found=False, composer_sha="changed"))

    def with_preview(token):
        reply = observed(found=False, composer_sha="changed")(token)
        reply["observe"]["previews"] = [{"alt": f"arena_{token}.png"}]
        return reply

    site.script["observe"] = [with_preview]
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict.failed and "prompt changed during the pause" in verdict.err
    assert "submit" not in site.calls


@pytest.mark.asyncio
async def test_cancel_during_pause_ends_before_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(fj, "PAUSE_POLL_S", 0.01)
    bridge = Bridge(tmp_path / "cfg")

    def baseline_then_pause(token):
        bridge._pause_requested = True
        asyncio.get_running_loop().call_later(0.03, setattr, bridge, "_cancel_requested", True)
        return baseline()

    site = happy_site(PROMPT, baseline=baseline_then_pause)
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict.err == "Cancelled" and site.calls == ["baseline"]


# ── security, reset seam, odd failures ───────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_security_waits_marks_the_pool_and_records_the_captcha(tmp_path, monkeypatch):
    from app.services import firefox_job_phases as ph
    monkeypatch.setattr(ph, "SECURITY_POLL_S", 0)
    monkeypatch.setattr("app.services.firefox_job_ctx.captcha_in_scope", lambda b: True)
    noted = []
    monkeypatch.setattr(ph, "note_captcha_event", lambda pool, tab, bridge, source: noted.append(tab))
    site = happy_site(PROMPT, baseline=[baseline(security=True), baseline()],
                      security=[{"security": {"security": True}}, {"security": {"security": False}}])
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False and site.calls.count("security") == 2 and len(noted) == 1
    assert ("CHECK_SECURITY", "success", "Security done") in bridge.actions


@pytest.mark.asyncio
async def test_security_not_cleared_within_the_cap_fails(tmp_path, monkeypatch):
    from app.services import firefox_job_phases as ph
    monkeypatch.setattr(ph, "SECURITY_POLL_S", 0)
    monkeypatch.setattr(ph, "pause_cap_seconds", lambda b: -1)
    monkeypatch.setattr("app.services.firefox_job_ctx.captcha_in_scope", lambda b: True)
    site = happy_site(PROMPT, baseline=baseline(security=True), security={"security": {"security": True}})
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "not cleared" in verdict.err and not verdict.review


@pytest.mark.asyncio
async def test_lane_reset_runs_new_chat_and_reports_a_dirty_page(tmp_path, monkeypatch):
    site = happy_site(PROMPT, reset=[{"reset": {"clean": True, "state": {}}},
                                     {"reset": {"clean": False, "state": {"previews": 1}}}])
    _, bridge, _, resets = await run(tmp_path, site, monkeypatch)
    assert await resets[0]() == (True, "New Chat — clean page verified")
    ok, reason = await resets[0]()
    assert ok is False and "not clean" in reason


@pytest.mark.asyncio
async def test_lane_reset_macro_without_answer_is_a_warning_reason(tmp_path, monkeypatch):
    site = happy_site(PROMPT, reset=("error", "E210", ()))
    _, _, _, resets = await run(tmp_path, site, monkeypatch)
    ok, reason = await resets[0]()
    assert ok is False and "E210" in reason


@pytest.mark.asyncio
async def test_tab_left_the_pool_is_a_named_failure(tmp_path, monkeypatch):
    from app.browser.page_pool import PagePool
    from tests.firefox_job_harness import image, source_image
    img = image(source_image(tmp_path))
    start = fj.JobStart(Bridge(tmp_path / "cfg"), PagePool(logger=lambda m, l="info": None),
                        "gone", img, "c1", PROMPT)
    reset_out = []
    verdict = await fj.run_job(start, reset_out)
    assert verdict.failed and "tab left the pool" in verdict.err and reset_out == []


@pytest.mark.asyncio
async def test_a_bug_inside_the_job_settles_honestly(tmp_path, monkeypatch):
    def boom(token):
        raise KeyError("surprise")

    site = happy_site(PROMPT, prompt=boom)
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "Firefox job crashed" in verdict.err and not verdict.review
    assert record(bridge) is None


@pytest.mark.asyncio
async def test_page_script_blocked_is_named(tmp_path, monkeypatch):
    site = happy_site(PROMPT, baseline={"baseline": {"ok": False, "error": "EvalError: CSP"}})
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "page script failed in baseline: EvalError: CSP" in verdict.err


def test_after_result_leaves_plain_outcomes_alone():
    from types import SimpleNamespace as NS
    img = NS(status="failed", error="x")
    fj.after_result(NS(bridge=NS(_cancel_requested=False), img=img), fj.Verdict(True, "x"))
    assert img.status == "failed"


def test_journal_record_reaches_disk_as_json(tmp_path):
    bridge = Bridge(tmp_path / "cfg")
    journal_of(bridge).create("c9", tab_id="t")
    saved = json.loads((tmp_path / "cfg" / "firefox_jobs.json").read_text(encoding="utf-8"))
    assert saved["jobs"]["c9"]["status"] == JobStatus.CREATED.value

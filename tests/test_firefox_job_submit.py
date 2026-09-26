"""The Firefox image job after the prompt: submit exactly once, correlation,
download / validate / save (design D-1 §18, 2026-09-25; split from
test_firefox_job.py by the 2026-09-26 refactor, R6)."""

import asyncio
from pathlib import Path

import pytest

from app.core.enums import JobStatus
from app.services import firefox_job_output as out
from tests.firefox_job_harness import (
    NEW_SRC, PROMPT, Bridge, happy_site, image_bytes, observed, record, run, sent,
)

pytestmark = pytest.mark.unit


# ── submit exactly once (§18) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_refusal_means_not_sent_and_a_plain_failure(tmp_path, monkeypatch):
    refused = {"guard": {"go": False, "bubble": False, "promptOk": False, "attachmentOk": True,
                         "sendEnabled": True}, "submit": {"ack": "", "bubble": False}}
    site = happy_site(PROMPT, submit=refused)
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and not verdict.review and "prompt ok=False" in verdict.err
    assert "observe" not in site.calls and record(bridge) is None


@pytest.mark.asyncio
async def test_submitted_is_journalled_before_the_send_macro(tmp_path, monkeypatch):
    seen = []

    def check(token):
        seen.append(record(bridge_box[0], token)["status"])
        return sent()

    bridge_box = [Bridge(tmp_path / "cfg")]
    site = happy_site(PROMPT, submit=check)
    await run(tmp_path, site, monkeypatch, bridge=bridge_box[0])
    assert seen == [JobStatus.SUBMITTED.value]


@pytest.mark.asyncio
async def test_lost_ack_then_bubble_seen_continues_without_resubmit(tmp_path, monkeypatch):
    site = happy_site(PROMPT, submit=sent(ack=""))
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False and site.calls.count("submit") == 1
    assert "submit uncertain" in bridge.text() and "confirmed late" in bridge.text()


@pytest.mark.asyncio
async def test_lost_ack_with_the_prompt_still_typed_is_a_safe_failure(tmp_path, monkeypatch):
    from app.services.firefox_job_phases import prompt_text, sha_of
    sha = sha_of(prompt_text(PROMPT))
    site = happy_site(PROMPT, submit=sent(ack=""),
                      observe=observed(found=False, bubble=False, composer_sha=sha))
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and not verdict.review and "not delivered" in verdict.err
    assert site.calls.count("submit") == 1 and site.calls.count("observe") == 2


@pytest.mark.asyncio
async def test_lost_ack_without_evidence_is_needs_review(tmp_path, monkeypatch):
    site = happy_site(PROMPT, submit=("error", "XClick failed", ()),
                      observe=observed(found=False, bubble=False, composer_sha="other"))
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.review and "submit uncertain" in verdict.err
    assert site.calls.count("submit") == 1
    assert record(bridge)["status"] == JobStatus.NEEDS_REVIEW.value   # evidence kept


# ── correlation (§18) ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_other_job_candidates_are_rejected_and_logged(tmp_path, monkeypatch):
    other = observed(found=False)

    def mismatch(token):
        reply = other(token)
        reply["observe"]["diag"]["mismatch"] = ["20260101-000000-AAAA"]
        return reply

    site = happy_site(PROMPT, observe=[mismatch, observed()])
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False
    assert "result candidate rejected — JOB-ID 20260101-000000-AAAA" in bridge.text()


@pytest.mark.asyncio
async def test_a_ready_result_of_another_job_is_never_taken(tmp_path, monkeypatch):
    site = happy_site(PROMPT, observe=[observed(job="someone-else"), observed()])
    verdict, _, img, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False and site.calls.count("observe") == 2


@pytest.mark.asyncio
async def test_generation_timeout_is_needs_review_never_resubmitted(tmp_path, monkeypatch):
    async def slow(token):
        await asyncio.sleep(0.4)
        return observed(found=False)(token)

    bridge = Bridge(tmp_path / "cfg")
    bridge.state.settings.timeouts["generation"] = 1
    site = happy_site(PROMPT, observe=slow)
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch, bridge=bridge)
    assert verdict.review and "timed out" in verdict.err and site.calls.count("submit") == 1


@pytest.mark.asyncio
async def test_page_error_after_submit_fails_the_job(tmp_path, monkeypatch):
    site = happy_site(PROMPT, observe=observed(found=False, errors="You have reached your daily limit"))
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "Page error" in verdict.err


@pytest.mark.asyncio
async def test_observe_macro_failing_three_times_is_needs_review(tmp_path, monkeypatch):
    site = happy_site(PROMPT, observe=("error", "E210 tab gone", ()))
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.review and "observe macro failed" in verdict.err
    assert site.calls.count("observe") == 3


# ── download / validate / save (§18) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_download_is_retried_then_succeeds(tmp_path, monkeypatch):
    fetched = [out.OutputError("got an HTML page, not an image"), image_bytes()]
    verdict, bridge, _, _ = await run(tmp_path, happy_site(PROMPT), monkeypatch, fetched=fetched)
    assert verdict.failed is False and "download invalid (attempt 1/3)" in bridge.text()


@pytest.mark.asyncio
async def test_download_never_valid_is_needs_review_with_the_src_kept(tmp_path, monkeypatch):
    fetched = [out.OutputError("partial download 10/99 bytes")]
    verdict, bridge, _, _ = await run(tmp_path, happy_site(PROMPT), monkeypatch, fetched=fetched)
    assert verdict.review and "partial download" in verdict.err
    assert record(bridge)["output_src"] == NEW_SRC


@pytest.mark.asyncio
async def test_corrupt_image_is_never_completed(tmp_path, monkeypatch):
    verdict, bridge, img, _ = await run(tmp_path, happy_site(PROMPT), monkeypatch, fetched=b"\x89PNG" + b"0" * 200)
    assert verdict.review and "download invalid" in verdict.err
    assert img.output_path is None and not list(tmp_path.glob("photo_AI*"))


@pytest.mark.asyncio
async def test_save_failure_keeps_the_staged_bytes_for_recovery(tmp_path, monkeypatch):
    def full(*_a, **_k):
        raise out.OutputError("save failed: [Errno 28] No space left on device")

    monkeypatch.setattr(out, "save_beside", full)
    verdict, bridge, _, _ = await run(tmp_path, happy_site(PROMPT), monkeypatch)
    assert verdict.review and "No space left" in verdict.err
    rec = record(bridge)
    assert rec["status"] == JobStatus.NEEDS_REVIEW.value
    assert Path(rec["download_path"]).read_bytes() == image_bytes()

"""The Firefox image job end to end (design D-1 §6/§14–§19, 2026-09-25).

Only `firefox_lane.run_phase` (the Ui.Vision launch) and the result GET are
faked; the journal, phases, correlation, validation and the atomic `_AI` save
are real. Acceptance §19: one image completes without manual steps, the
attachment is positively verified, the message is sent ONCE, the result is
proven new + ours, it is saved atomically beside the source, and an invalid
or uncertain result is never completed.
"""

import asyncio
import json
from pathlib import Path

import pytest

from app.core.enums import ImageStatus, JobStatus
from app.services import firefox_job as fj
from app.services import firefox_job_output as out
from app.services.firefox_job_journal import journal_of
from tests.firefox_job_harness import (
    NEW_SRC, Bridge, attached, baseline, happy_site, image_bytes, observed, prompt_ok, run, sent,
)

pytestmark = pytest.mark.unit

PROMPT = "[JOB-ID: c1]\nmake it red"
CHROME_ORDER = ["OBSERVE_BASELINE", "ATTACH_IMAGE", "VERIFY_ATTACHMENT", "INSERT_PROMPT",
                "VERIFY_PROMPT", "SUBMIT", "WAIT_OUTPUT", "DOWNLOAD", "VALIDATE", "SAVE"]


def blocks(bridge, status="success"):
    return [b for b, s, _ in bridge.actions if s == status]


def record(bridge, corr="c1"):
    return journal_of(bridge).get(corr)


# ── happy path (§19) ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_image_completes_sent_once_and_saved_beside_the_source(tmp_path, monkeypatch):
    site = happy_site(PROMPT)
    verdict, bridge, img, _ = await run(tmp_path, site, monkeypatch)
    assert verdict == fj.Verdict(False)
    saved = Path(img.output_path)
    assert saved == tmp_path / "photo_AI.png" and saved.read_bytes() == image_bytes()
    assert site.calls == ["baseline", "attach", "prompt", "submit", "observe"]
    assert site.calls.count("submit") == 1                        # exactly one send macro
    assert blocks(bridge) == CHROME_ORDER                          # Chrome's block ids, in order
    assert record(bridge) is None                                  # journal settled
    assert not (tmp_path / "cfg" / "firefox_jobs" / "c1").exists()
    assert not list((tmp_path / "cfg" / "uivision" / "uploads").glob("*"))  # staged copy dropped
    assert "🦊 [c1]" in bridge.text()


@pytest.mark.asyncio
async def test_the_dialog_receives_the_unique_staged_copy(tmp_path, monkeypatch):
    site = happy_site(PROMPT)
    await run(tmp_path, site, monkeypatch)
    attach = next(p for p in site.phases if p.phase == "attach")
    typed = [c["Target"] for c in attach.commands if c["Command"] == "XType"]
    assert typed[0].endswith("arena_c1.png") and str(typed[0]).isascii()
    assert typed[1] == "${KEY_ENTER}"


@pytest.mark.parametrize("name,fmt,ext", [("p.jpg", "JPEG", ".jpeg"), ("p.jpeg", "JPEG", ".jpeg"),
                                          ("p.webp", "WEBP", ".webp")])
@pytest.mark.asyncio
async def test_jpeg_and_webp_sources_upload_under_their_own_extension(tmp_path, monkeypatch,
                                                                      name, fmt, ext):
    src_ext = "." + name.rsplit(".", 1)[1]
    site = happy_site(PROMPT, ext=src_ext)
    verdict, _, img, _ = await run(tmp_path, site, monkeypatch, src_name=name, fmt=fmt)
    assert verdict.failed is False and img.output_path.endswith("p_AI.png")  # result format decides


@pytest.mark.asyncio
async def test_existing_ai_file_is_never_overwritten(tmp_path, monkeypatch):
    (tmp_path / "photo_AI.png").write_bytes(b"old")
    verdict, _, img, _ = await run(tmp_path, happy_site(PROMPT), monkeypatch)
    assert verdict.failed is False and img.output_path.endswith("photo_AI_2.png")
    assert (tmp_path / "photo_AI.png").read_bytes() == b"old"


# ── source + attachment (§18) ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_source_fails_before_any_macro(tmp_path, monkeypatch):
    site = happy_site(PROMPT)
    bridge = Bridge(tmp_path / "cfg")
    from tests.firefox_job_harness import TAB, firefox_pool, image, wire
    wire(monkeypatch, site)
    img = image(tmp_path / "gone.png")
    verdict = await fj.run_job(fj.JobStart(bridge, firefox_pool(), TAB, img, "c1", PROMPT), [])
    assert verdict.failed and "missing" in verdict.err and site.calls == []


@pytest.mark.parametrize("name,fmt,needle", [("a.gif", "GIF", "unsupported"),
                                             ("a.jpg", "PNG", "extension says JPEG")])
@pytest.mark.asyncio
async def test_unsupported_or_mislabelled_source_fails_before_any_macro(tmp_path, monkeypatch,
                                                                       name, fmt, needle):
    site = happy_site(PROMPT)
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch, src_name=name, fmt=fmt)
    assert verdict.failed and needle in verdict.err and site.calls == []


@pytest.mark.asyncio
async def test_stale_attachment_gets_new_chat_then_a_clean_baseline(tmp_path, monkeypatch):
    stale = baseline(previews=[{"alt": "old.png"}])
    site = happy_site(PROMPT, baseline=[stale, baseline()])
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False
    assert site.calls[:3] == ["baseline", "reset", "baseline"]
    assert "stale attachment" in bridge.text()


@pytest.mark.asyncio
async def test_stale_attachment_that_survives_new_chat_fails_unsent(tmp_path, monkeypatch):
    site = happy_site(PROMPT, baseline=baseline(previews=[{"alt": "old.png"}]))
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "stale attachment" in verdict.err
    assert "submit" not in site.calls and record(bridge) is None


@pytest.mark.parametrize("previews,needle", [
    ([{"alt": "someone_else.png"}], "wrong attachment preview"),
    ([{"alt": "arena_c1.png"}, {"alt": "x.png"}], "multiple attachments"),
    ([{"alt": "arena_c1.png"}, {"alt": "arena_c1.png"}], "multiple attachments"),
])
@pytest.mark.asyncio
async def test_wrong_or_extra_preview_fails_before_submit(tmp_path, monkeypatch, previews, needle):
    site = happy_site(PROMPT, attach={"attach": {"previews": previews, "matched": 0}})
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and needle in verdict.err and "submit" not in site.calls


@pytest.mark.asyncio
async def test_missing_preview_retries_the_upload_once_then_fails(tmp_path, monkeypatch):
    site = happy_site(PROMPT, attach={"attach": {"previews": [], "matched": 0}})
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert site.calls.count("attach") == 2
    assert verdict.failed and "not visible" in verdict.err and "submit" not in site.calls


@pytest.mark.asyncio
async def test_composer_missing_fails_as_page_not_ready(tmp_path, monkeypatch):
    site = happy_site(PROMPT, baseline=baseline(composer_len=-1))
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "not ready" in verdict.err and site.calls == ["baseline"]


# ── prompt (§18) ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiline_unicode_prompt_is_verified_by_utf16_length_and_sha(tmp_path, monkeypatch):
    prompt = "[JOB-ID: c1]\r\nŽluťoučký kůň 😀\nřádek 3"
    site = happy_site(prompt)
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch, prompt=prompt)
    assert verdict.failed is False
    phase = next(p for p in site.phases if p.phase == "prompt")
    assert "Arena_Job_Prompt" == phase.name
    assert "VERIFY_PROMPT" in blocks(bridge)


@pytest.mark.asyncio
async def test_truncated_readback_reinserts_once_then_passes(tmp_path, monkeypatch):
    bad = {"prompt": {"ok": False, "len": 3, "sha256": "x", "error": ""}}
    site = happy_site(PROMPT, prompt=[bad, prompt_ok(PROMPT)])
    verdict, bridge, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed is False and site.calls.count("prompt") == 2
    assert "readback mismatch" in bridge.text()


@pytest.mark.asyncio
async def test_duplicated_readback_twice_fails_before_submit(tmp_path, monkeypatch):
    dup = {"prompt": {"ok": False, "len": 60, "sha256": "dup", "error": ""}}
    site = happy_site(PROMPT, prompt=dup)
    verdict, _, _, _ = await run(tmp_path, site, monkeypatch)
    assert verdict.failed and "readback mismatch" in verdict.err and "submit" not in site.calls


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

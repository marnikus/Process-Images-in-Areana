"""The Firefox image job end to end (design D-1 §6/§14–§19, 2026-09-25).

Only `firefox_lane.run_phase` (the Ui.Vision launch) and the result GET are
faked; the journal, phases, correlation, validation and the atomic `_AI` save
are real. Acceptance §19: one image completes without manual steps, the
attachment is positively verified, the message is sent ONCE, the result is
proven new + ours, it is saved atomically beside the source, and an invalid
or uncertain result is never completed.
"""

from pathlib import Path

import pytest

from app.services import firefox_job as fj
from tests.firefox_job_harness import (
    PROMPT, Bridge, baseline, blocks, happy_site, image_bytes, prompt_ok, record, run,
)

pytestmark = pytest.mark.unit

CHROME_ORDER = ["OBSERVE_BASELINE", "ATTACH_IMAGE", "VERIFY_ATTACHMENT", "INSERT_PROMPT",
                "VERIFY_PROMPT", "SUBMIT", "WAIT_OUTPUT", "DOWNLOAD", "VALIDATE", "SAVE"]


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
    pasted = [c["Target"] for c in attach.commands if c["Value"] == "!clipboard"]  # live fix 2026-09-26
    assert len(pasted) == 1 and pasted[0].endswith('arena_c1.png"') and pasted[0].isascii()
    assert "\\" not in pasted[0]  # forward slashes only: no escape can eat the path
    assert not any("arena_c1" in c["Target"] for c in attach.commands if c["Command"] == "XType")


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

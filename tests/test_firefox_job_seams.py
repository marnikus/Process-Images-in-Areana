"""Characterization tests for the Firefox job refactor seams (audit S0, 2026-09-26).

`docs/archive/2026-09-26-firefox-job-refactor/audit.md` §5: every behaviour the
refactor steps R1–R4 touch is pinned here on the code as it was, so a
structural step that changes an outcome fails loudly. Behaviour steps (B1–B3)
change a pin here deliberately, in their own commit.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.enums import ImageStatus, JobStatus
from app.core.state_machine import validate_job_transition
from app.services import firefox_job as fj
from app.services import firefox_job_output as out
from app.services import firefox_job_recovery as rec
from app.services import firefox_lane as fl
from app.services.firefox_job_ctx import FfJob, JobFailure
from app.services.firefox_job_journal import POST_SUBMIT, JobJournal, journal_of
from app.services.firefox_job_phases import check_attachment
from tests.firefox_job_harness import Bridge, happy_site, image, image_bytes, run, source_image
from tests.test_firefox_lane import CfgBridge, ff_page

PROMPT = "[JOB-ID: c1]\nmake it red"
OURS = "arena_c1.png"


def _job(journal=None, bridge=None) -> FfJob:
    return FfJob(bridge=bridge, pool=None, page=None, img=None, corr="c1", prompt=PROMPT,
                 journal=journal or JobJournal(), staged=f"/u/{OURS}")


def _outcome(previews) -> str:
    try:
        check_attachment(_job(), {"previews": [{"alt": a} for a in previews]})
    except JobFailure as exc:
        return str(exc)
    return "ok"


# ---- check_attachment: the full truth table (R1 simplifies its conditions) ----

@pytest.mark.parametrize("previews, expected", [
    ([OURS], "ok"),
    ([], "attachment not visible after the upload"),
    (["other.png"], "wrong attachment preview: other.png"),
    ([""], "wrong attachment preview: unnamed blob"),
    ([OURS, OURS], "multiple attachments in the composer (2)"),
    ([OURS, "other.png"], "multiple attachments in the composer (2)"),
    (["other.png", OURS], "multiple attachments in the composer (2)"),
    (["a.png", "b.png"], "wrong attachment preview: a.png"),
    ([OURS, "a.png", "b.png"], "multiple attachments in the composer (3)"),
])
def test_check_attachment_truth_table(previews, expected):
    assert _outcome(previews) == expected


# ---- settle: review vs plain failure (R2 unifies the two settle paths) ----

def test_every_post_submit_status_can_become_needs_review():
    """The invariant that keeps a sent job's evidence: a refused review move would forget it."""
    assert all(validate_job_transition(s, JobStatus.NEEDS_REVIEW.value) for s in POST_SUBMIT)


def _journal_at(status: str) -> JobJournal:
    journal = JobJournal()
    journal.create("c1")
    chain = ["baseline_captured", "attaching", "attachment_verified", "prompt_inserted",
             "prompt_verified", "submitted"]
    for step in chain[: chain.index(status) + 1]:
        assert journal.advance("c1", step)
    return journal


def test_a_review_failure_before_submit_settles_as_a_plain_forgotten_failure(tmp_path):
    job = _job(_journal_at("baseline_captured"), Bridge(tmp_path / "cfg"))
    verdict = fj._settle_failure(job, "security check not cleared", True)
    assert (verdict.failed, verdict.review, verdict.err) == (True, False, "security check not cleared")
    assert job.journal.get("c1") is None and not job.skip_reset


def test_a_review_failure_after_submit_keeps_the_record(tmp_path):
    job = _job(_journal_at("submitted"), Bridge(tmp_path / "cfg"))
    verdict = fj._settle_failure(job, "lost", True)
    assert (verdict.failed, verdict.review, verdict.err) == (True, True, "needs review — lost")
    assert job.journal.get("c1")["status"] == JobStatus.NEEDS_REVIEW.value
    assert job.review and job.skip_reset


@pytest.mark.parametrize("status, review, err", [
    ("prompt_verified", False, "Cancelled"),
    ("submitted", True, fj.CANCEL_REVIEW),
])
def test_cancel_settles_by_the_submit_line(tmp_path, status, review, err):
    job = _job(_journal_at(status), Bridge(tmp_path / "cfg"))
    verdict = fj._settle_cancel(job)
    assert (verdict.failed, verdict.review, verdict.err) == (True, review, err)
    assert (job.journal.get("c1") is not None) == review


# ---- submit: the exact refusal text (R1 extracts its formatting) ----

@pytest.mark.asyncio
async def test_guard_refusal_text_is_exact(tmp_path, monkeypatch):
    refused = {"guard": {"go": False, "bubble": False, "promptOk": True, "attachmentOk": False,
                         "sendEnabled": True}, "submit": {"ack": "", "bubble": False}}
    verdict, *_ = await run(tmp_path, happy_site(PROMPT, submit=refused), monkeypatch)
    assert verdict.err == ("submit guard refused — not sent (prompt ok=True, attachment ok=False, "
                           "send enabled=True)")


@pytest.mark.asyncio
@pytest.mark.parametrize("ack, logged", [("bubble", "submitted (ack: bubble)"),
                                         ("cleared", "submitted (ack: cleared)")])
async def test_submit_ack_wording(tmp_path, monkeypatch, ack, logged):
    sent = {"guard": {"go": True, "bubble": False}, "submit": {"ack": ack, "bubble": ack == "bubble"}}
    verdict, bridge, *_ = await run(tmp_path, happy_site(PROMPT, submit=sent), monkeypatch)
    assert not verdict.failed and ("SUBMIT", "success", logged) in bridge.actions


# ---- bridge seams: a failing bridge never breaks the job (R3 moves these) ----

class BrokenBridge(Bridge):
    """Every bridge seam the job touches raises."""

    def _log(self, message, level="info"):
        raise RuntimeError("log down")

    def _emit_job_action_status(self, action):
        raise RuntimeError("emit down")

    def _emit_pool_status(self):
        raise RuntimeError("pool push down")

    def _save_arena(self):
        raise RuntimeError("disk down")


@pytest.mark.asyncio
async def test_a_broken_bridge_never_breaks_a_job(tmp_path, monkeypatch):
    bridge = BrokenBridge(tmp_path / "cfg")
    verdict, _, img, _ = await run(tmp_path, happy_site(PROMPT), monkeypatch, bridge=bridge)
    assert not verdict.failed and img.output_path.endswith("photo_AI.png")


def test_after_result_survives_a_broken_persist(tmp_path):
    bridge = BrokenBridge(tmp_path / "cfg")
    img = image(source_image(tmp_path))
    ctx = type("Ctx", (), {"bridge": bridge, "img": img})()
    fj.after_result(ctx, fj.Verdict(True, "needs review — x", True))
    assert img.status == ImageStatus.NEEDS_REVIEW.value


def test_recovery_survives_a_broken_bridge(tmp_path):
    src = source_image(tmp_path)
    img = image(src)
    bridge = BrokenBridge(tmp_path / "cfg", [img])
    journal_of(bridge).create("c1", image_id=img.id, image_path=str(src))
    assert asyncio.run(rec.recover_firefox_jobs(bridge)) == {"dropped": 1}


# ---- recovery: the download timeout it uses today (B1 changes this pin) ----

def test_recovery_fetch_timeout_is_sixty_seconds(tmp_path, monkeypatch):
    seen = []

    def fetch(src, timeout, opener=None):
        seen.append(timeout)
        return image_bytes()

    monkeypatch.setattr(out, "fetch", fetch)
    src = source_image(tmp_path)
    img = image(src)
    bridge = Bridge(tmp_path / "cfg", [img])   # settings say download = 5
    journal = journal_of(bridge)
    journal.create("c1", image_id=img.id, image_path=str(src))
    for step in ["baseline_captured", "attaching", "attachment_verified", "prompt_inserted",
                 "prompt_verified", "submitted", "waiting_generation", "output_detected"]:
        journal.advance("c1", step)
    journal.update("c1", output_src="https://r2/new.png")
    assert asyncio.run(rec.recover_firefox_jobs(bridge)) == {"completed": 1}
    assert seen == [60]


# ---- lane: both runners refuse browser storage with their own words (R4 merges them) ----

@pytest.mark.asyncio
async def test_identify_refuses_browser_storage_before_any_launch():
    bridge = CfgBridge(cfg={"storage": "browser"})
    kind, msg, lines = await fl.run_identify(bridge, ff_page(), "payload")
    assert (kind, msg, lines) == ("blocked", "identify needs hard-drive macro storage (xfile)", ())


@pytest.mark.asyncio
async def test_phase_refuses_browser_storage_with_the_job_wording():
    from app.browser.uivision import job_macros as jm
    bridge = CfgBridge(cfg={"storage": "browser"})
    phase = jm.probe_macro("c1", "baseline", "1")
    kind, msg, _ = await fl.run_phase(bridge, ff_page(), phase, "c1")
    assert (kind, msg) == ("blocked", "the image job needs hard-drive macro storage (xfile)")

"""Firefox job crash recovery — inspect before any retry (design §16, 2026-09-25).

The live loop reconciles the journal BEFORE `processing` leftovers are
re-queued: a result already saved / staged / fetchable is completed without a
resubmit, an unresolved post-submit job becomes needs_review, and a pre-submit
job is simply re-queued. Nothing here ever launches a macro.
"""

import asyncio

import pytest

from app.core.enums import ImageStatus, JobStatus
from app.services import firefox_job_output as out
from app.services import firefox_job_recovery as rec
from app.services.firefox_job_journal import journal_of
from tests.firefox_job_harness import Bridge, image, image_bytes, source_image

pytestmark = pytest.mark.unit

GOOD = image_bytes()


def setup(tmp_path, status, **fields):
    src = source_image(tmp_path)
    img = image(src)
    bridge = Bridge(tmp_path / "cfg", [img])
    journal = journal_of(bridge)
    journal.create("c1", image_id=img.id, image_path=str(src))
    chain = ["baseline_captured", "attaching", "attachment_verified", "prompt_inserted",
             "prompt_verified", "submitted", "waiting_generation", "output_detected",
             "downloading", "validating", "saving"]
    for step in chain[: chain.index(status) + 1] if status in chain else []:
        assert journal.advance("c1", step)
    if status == JobStatus.NEEDS_REVIEW.value:
        for step in chain[:6] + ["needs_review"]:
            assert journal.advance("c1", step)
    journal.update("c1", **fields)
    return bridge, img, src


def run(bridge):
    return asyncio.run(rec.recover_firefox_jobs(bridge))


def test_final_file_already_saved_is_reconciled_as_completed(tmp_path):
    bridge, img, src = setup(tmp_path, "saving", bytes_sha256=out.sha256(GOOD))
    (tmp_path / "photo_AI.png").write_bytes(GOOD)
    assert run(bridge) == {"completed": 1}
    assert img.status == ImageStatus.COMPLETED.value and img.output_path.endswith("photo_AI.png")
    assert journal_of(bridge).get("c1") is None and "no resubmit" in bridge.text()
    assert len(list(tmp_path.glob("photo_AI*"))) == 1                  # nothing re-saved


def test_downloaded_but_not_saved_completes_the_atomic_save(tmp_path):
    staged = out.stage_bytes(tmp_path / "cfg" / "firefox_jobs" / "c1", GOOD)
    bridge, img, _ = setup(tmp_path, "validating", bytes_sha256=out.sha256(GOOD), download_path=str(staged))
    assert run(bridge) == {"completed": 1}
    assert (tmp_path / "photo_AI.png").read_bytes() == GOOD
    assert not staged.parent.exists()                                  # job folder cleaned


def test_generated_but_not_downloaded_is_collected_without_resubmit(tmp_path, monkeypatch):
    monkeypatch.setattr(out, "fetch", lambda src, timeout, opener=None: GOOD)
    bridge, img, _ = setup(tmp_path, "output_detected", output_src="https://r2/new.png")
    assert run(bridge) == {"completed": 1} and img.output_path.endswith("photo_AI.png")


def test_submitted_without_any_evidence_becomes_needs_review(tmp_path):
    bridge, img, _ = setup(tmp_path, "submitted")
    assert run(bridge) == {"needs_review": 1}
    assert img.status == ImageStatus.NEEDS_REVIEW.value and "interrupted after submit" in img.error
    assert journal_of(bridge).get("c1")["status"] == JobStatus.NEEDS_REVIEW.value


def test_a_review_record_without_evidence_stays_as_it_is(tmp_path):
    bridge, img, _ = setup(tmp_path, JobStatus.NEEDS_REVIEW.value)
    img.status = ImageStatus.NEEDS_REVIEW.value
    assert run(bridge) == {"needs_review": 1}
    assert journal_of(bridge).get("c1")["status"] == JobStatus.NEEDS_REVIEW.value


def test_before_submit_the_record_is_dropped_and_the_staged_copy_removed(tmp_path):
    staged = tmp_path / "arena_c1.png"
    staged.write_bytes(GOOD)
    bridge, img, _ = setup(tmp_path, "prompt_verified", staged_upload=str(staged))
    assert run(bridge) == {"dropped": 1}
    assert journal_of(bridge).get("c1") is None and not staged.exists()
    assert img.status == "processing"          # left for recover_stale_processing → pending


def test_a_failed_collection_becomes_needs_review_with_the_reason(tmp_path, monkeypatch):
    def expired(src, timeout, opener=None):
        raise out.OutputError("HTTP 403")

    monkeypatch.setattr(out, "fetch", expired)
    bridge, img, _ = setup(tmp_path, "output_detected", output_src="https://r2/new.png")
    assert run(bridge) == {"needs_review": 1} and "HTTP 403" in img.error


def test_a_record_whose_image_left_the_queue_is_reviewed(tmp_path):
    bridge, img, _ = setup(tmp_path, "waiting_generation")
    bridge.state.images.clear()
    assert run(bridge) == {"needs_review": 1}


def test_one_broken_record_never_stops_the_others(tmp_path, monkeypatch):
    bridge, img, _ = setup(tmp_path, "submitted")

    async def boom(bridge, journal, record):
        raise RuntimeError("disk vanished")

    monkeypatch.setattr(rec, "recover_one", boom)
    assert run(bridge) == {"error": 1} and "recovery failed: disk vanished" in bridge.text()


def test_nothing_open_means_nothing_saved(tmp_path):
    bridge = Bridge(tmp_path / "cfg")
    assert run(bridge) == {} and bridge.saves == 0


def test_suffix_falls_back_to_ai_without_settings():
    from types import SimpleNamespace as NS
    assert rec._suffix(NS(state=NS())) == "_AI"


def test_the_live_loop_reconciles_before_requeueing(monkeypatch):
    """Order matters: a submitted Firefox image must not be reset to pending first."""
    from app.services.live import supervisor as sup
    order = []

    async def recover(bridge):
        order.append("firefox")

    monkeypatch.setattr(sup, "recover_firefox_jobs", recover)
    monkeypatch.setattr(sup, "recover_stale_processing", lambda b: order.append("stale"))
    monkeypatch.setattr(sup, "set_run_state", lambda b, s: None)
    monkeypatch.setattr(sup, "is_live", lambda b: False)

    class Bus:
        def attach(self, loop):
            pass

    monkeypatch.setattr(sup, "live_bus", lambda b: Bus())
    try:
        asyncio.run(sup.run_live(object()))
    except Exception:
        pass
    assert order[:2] == ["firefox", "stale"]

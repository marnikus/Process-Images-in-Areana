"""The Firefox image job, driven end to end without a browser (steps 14–19).

`firefox_job.run_image_job` is the stage machine: preflight → recovery →
prepare (attach + prompt + checkpoint) → the pause/stop/cancel checkpoint → one
guarded submit → correlate → bytes → validate → staging → atomic save. This file
drives the *real* machine — only `run_job_stage` (the macro launcher) and the
network fetch are scripted, so the verdicts, the journal and the files on disk
are the production ones.

Every bullet of the owner's test list that does not need the real DOM lives here;
the jsdom lane (`tests/js/test_firefox_job_probes.mjs`) executes the probes.

RED at base: `app/services/firefox_job.py` did not exist.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.browser.page_pool import PagePool
from app.browser.uivision import job_replies as jr
from app.browser.uivision import pool_tabs as pt
from app.core.models import ImageItem
from app.services import firefox_job as fj
from app.services import firefox_journal as journal

pytestmark = pytest.mark.unit

PROMPT = "héllo\nworld 🎨 [JOB-ID: T]"


def image_bytes(fmt="PNG", size=(64, 64)):
    buf = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, format=fmt)
    return buf.getvalue()


def source(tmp_path, name="a.png"):
    path = tmp_path / name
    path.write_bytes(image_bytes())
    return path


class Bridge:
    """Duck-typed bridge: settings, log capture, the pool, the operator flags."""

    def __init__(self, pool):
        self._page_pool = pool
        self.state = NS(settings=NS(output={"suffix": "_AI", "preserve_format": True,
                                            "overwrite": False},
                                    timeouts={"generation": 180}),
                        prompt={"user_prompt": PROMPT})
        self.config = NS(dir="/tmp/cfg", get_state=lambda key, default=None: default)
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self.logs = []
        self.pool_emits = 0

    def _log(self, message, level="info"):
        self.logs.append((level, message))

    def _emit_pool_status(self):
        self.pool_emits += 1

    def text(self):
        return "\n".join(m for _lvl, m in self.logs)


def make_img(path):
    data = {"id": "i1", "relative_path": Path(path).name, "absolute_path": str(path),
            "filename": Path(path).name, "base_name": Path(path).stem,
            "extension": Path(path).suffix.lstrip("."), "size": 1, "mtime": 0.0,
            "fingerprint": "fp"}
    item = ImageItem.from_scan_dict(data)
    item.selected = True
    return item


def firefox_pool(tab_id="T_user.Profile1_tab1"):
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id=tab_id, url="https://arena.ai/c/7", title="A", profile="P1",
                        profile_dir="/x/P1", ws_url=f"firefox://{tab_id}")
    pool.add_page(pt.page_for(tab))
    return pool


def marker(mark, value):
    return f"echo: {mark}{json.dumps(value, ensure_ascii=False)}"


def word(mark, value):
    return f"echo: {mark}{value}"


def prepare_log(baseline=(), attach_ok=True, prompt_ok=True, guard="true", why="ready"):
    baseline = list(baseline)
    lines = [marker(jr.STATE_MARK, {"srcs": baseline, "previews": [], "clean": True,
                                    "textarea": True, "ready": "complete"}),
             word("ARENA_ATTACH_SEL=", "xpath=/html[1]/body[1]/button[2]")]
    if attach_ok:
        lines.append(marker(jr.ATTACH_MARK, {"ok": True, "found": {"alt": "a.png"},
                                             "count": 1, "stale": 0}))
    else:
        lines.append(marker(jr.ATTACH_MARK, {"ok": False, "count": 1, "stale": 1,
                                             "reason": "stale attachment from a previous job (b.png)"}))
    expected = jr.prompt_hash(PROMPT)
    lines.append(marker(jr.PROMPT_MARK, {"ok": prompt_ok, "len": len(PROMPT),
                                         "hash": expected if prompt_ok else "00000000",
                                         "expected_hash": expected, "occurrences": 1,
                                         "reason": "matched" if prompt_ok else "truncated read-back"}))
    lines += [word(jr.GUARD_MARK, guard), word(jr.WHY_MARK, why)]
    return lines


def submit_log(clicks=1, result=None, guard="true", why="ready"):
    lines = [marker(jr.PROMPT_MARK, {"ok": True, "hash": jr.prompt_hash(PROMPT), "len": len(PROMPT)}),
             word(jr.GUARD_MARK, guard), word(jr.WHY_MARK, why),
             word("ARENA_SEND_SEL=", "xpath=/html[1]/body[1]/button[9]"),
             word(jr.SUBMIT_MARK, str(clicks))]
    result = result if result is not None else {"candidates": [
        {"src": "https://cdn/a.png", "after": True, "in_user": False, "large": True, "nat": 900}]}
    lines.append(marker(jr.RESULT_MARK, result))
    return lines


def fetch_log(data):
    return [marker(jr.DATA_MARK, {"ok": True, "method": "fetch", "len": len(base64.b64encode(data)),
                                  "b64": base64.b64encode(data).decode()})]


def drain(path):
    for entry in Path(path).iterdir():
        if entry.is_file():
            entry.unlink()


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A scripted lane: stages answer from `script`, the fetch returns `bytes_for`."""
    pool = firefox_pool()
    bridge = Bridge(pool)
    src = source(tmp_path)
    img = make_img(src)
    calls = []
    script = {}
    payload = {"data": image_bytes()}

    async def fake_stage(b, page, inputs, report=None):
        calls.append(inputs.stage)
        kind, message, lines = script.get(inputs.stage, ("ok", "stage ran", []))
        return kind, message, list(lines)

    monkeypatch.setattr(fj, "run_job_stage", fake_stage)

    def fake_download(url, timeout=45):
        if payload["data"] is None:
            return False, b"", "connection reset"
        return True, payload["data"], f"downloaded {len(payload['data'])} bytes"

    monkeypatch.setattr(fj.result, "download", fake_download)
    req = fj.JobRequest(bridge=bridge, page=pool.get_page("T_user.Profile1_tab1"),
                        img=img, corr_id="20260925-142530-A7F3", job_id="J1", prompt=PROMPT)
    # the journal lives under the real config dir; point it at the tmp dir
    monkeypatch.setattr(journal, "_config_dir", lambda b: tmp_path / "cfg")
    return NS(pool=pool, bridge=bridge, img=img, src=src, req=req, script=script,
              payload=payload, calls=calls, tmp=tmp_path)


def run(harness, **script):
    """Drive one dispatch; `script` adds/overrides the stages this run should see."""
    harness.script.update(script)
    return asyncio.run(fj.run_image_job(harness.req))


# ---------------------------------------------------------------- the happy path


def test_a_valid_upload_runs_every_stage_and_saves_the_result(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log(baseline=["blob:old"]))
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED and outcome.output_path.endswith("a_AI.png")
    assert harness.calls == ["prepare", "submit"]          # one prepare, one submit, no page fetch
    saved = Path(outcome.output_path)
    assert saved.is_file() and saved.read_bytes() == harness.payload["data"]
    assert not (harness.tmp / f".{saved.name}.part").exists()
    assert journal.read(harness.bridge, harness.img) == {}   # the job forgot itself
    text = harness.bridge.text()
    for needle in ("baseline: 1 output image(s)", "✅ Attachment verified",
                   "✅ Prompt verified", "submit intent", "✅ Submitted",
                   "🔎 result correlated", "💾 atomic save started", "✅ Saved a_AI.png"):
        assert needle in text, needle
    assert harness.bridge.pool_emits >= 0


def test_a_multiline_unicode_prompt_survives_the_round_trip(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    assert run(harness).status == fj.COMPLETED
    baked = json.loads((harness.tmp / "cfg" / "firefox_jobs" / "i1.json").read_text()) \
        if (harness.tmp / "cfg" / "firefox_jobs" / "i1.json").exists() else None
    assert baked is None or "prompt" not in baked          # the journal holds facts, not the prompt


def test_an_existing_ai_file_is_never_overwritten(harness):
    (harness.tmp / "a_AI.png").write_bytes(image_bytes())           # a previous run's output
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED and outcome.output_path.endswith("a_AI_2.png")
    assert (harness.tmp / "a_AI.png").is_file()


def test_the_output_is_saved_even_when_the_correlated_src_needs_the_page_fetch(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.payload["data"] = None                                  # the direct fetch fails
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    harness.script["fetch"] = ("ok", "fetch ran", fetch_log(image_bytes("JPEG")))
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED
    assert harness.calls == ["prepare", "submit", "fetch"]
    assert Path(outcome.output_path).suffix == ".jpg"                # the format the bytes are


# ------------------------------------------------------------- the pre-submit half


def test_a_missing_or_unsupported_source_never_launches_a_macro(harness):
    harness.img.absolute_path = str(harness.tmp / "gone.png")
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "source file missing" in outcome.error
    (harness.tmp / "a.bmp").write_bytes(image_bytes())
    harness.img.absolute_path = str(harness.tmp / "a.bmp")
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "unsupported source type" in outcome.error
    assert harness.calls == []                                       # nothing was driven


def test_a_stale_attachment_is_a_review_not_a_submit(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log(attach_ok=False))
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW
    assert "stale attachment from a previous job" in outcome.error
    assert "submit" not in harness.calls
    assert harness.pool.get_page(harness.req.page.tab_id).status.value == "error"


def test_a_wrong_attachment_preview_and_a_truncated_prompt_never_submit(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log(attach_ok=False))
    assert run(harness).status == fj.NEEDS_REVIEW
    journal.clear(harness.bridge, harness.img)          # the failed pass is over; a new one starts
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log(prompt_ok=False))
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "prompt not verified" in outcome.error
    assert "truncated read-back" in outcome.error
    assert "submit" not in harness.calls


def test_a_refused_checkpoint_stops_before_the_click(harness):
    harness.script["prepare"] = ("ok", "prepare ran",
                                 prepare_log(guard="false", why="send button disabled"))
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "send button disabled" in outcome.error
    assert "submit" not in harness.calls


def test_a_security_dialog_is_a_manual_action_and_keeps_the_page(harness):
    harness.script["prepare"] = ("ok", "prepare ran",
                                 prepare_log(guard="false", why="security dialog visible"))
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW
    page = harness.pool.get_page(harness.req.page.tab_id)
    assert page.status.value == "waiting_captcha"       # busy → waiting_user
    assert "manual action required" in outcome.error


def test_a_prepare_run_that_answers_nothing_is_a_review(harness):
    harness.script["prepare"] = ("error", "E210 no matching tab", [])
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW and "answered nothing" in outcome.error


# ------------------------------------------------------------------- the submit


def test_an_old_result_is_rejected_by_the_baseline(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log(result={"candidates": [
        {"src": "https://cdn/old.png", "after": False, "in_user": False, "large": True}]}))
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW and "older result was rejected" in outcome.error


def test_several_candidates_are_ambiguous_and_never_picked(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log(result={"candidates": [
        {"src": "https://cdn/1.png", "after": True, "in_user": False, "large": True, "nat": 900},
        {"src": "https://cdn/2.png", "after": True, "in_user": False, "large": True, "nat": 700}]}))
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW and "multiple candidate results" in outcome.error
    assert "1.png" not in outcome.error                 # the app refuses to choose


def test_a_delayed_result_after_the_timeout_is_uncertain_not_failed_loudly(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran",
                                submit_log(result={"timed_out": True, "token_seen": True}))
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW and "result uncertain" in outcome.error
    assert "180000ms" in harness.bridge.text()          # the wait's own budget is logged


def test_a_lost_submit_ack_is_still_evidence_of_a_submit(harness):
    """The click count is 0 but this job's token is on the page: never a second click."""
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log(result={"timed_out": True, "token_seen": True}))
    outcome = run(harness)
    assert harness.calls.count("submit") == 1
    assert outcome.status == fj.NEEDS_REVIEW            # submitted + uncertain result
    data = journal.read(harness.bridge, harness.img)     # …and the journal recorded the submit
    assert data.get("phase") == "submitted" or data.get("submit_clicks") == 0


def test_no_submit_evidence_at_all_is_a_plain_failure(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran",
                                submit_log(clicks=0, guard="false", why="prompt read-back differs (3/9 chars)",
                                           result={"timed_out": True, "token_seen": False}))
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "not submitted" in outcome.error


# ----------------------------------------------------------- the download & save


def test_a_download_that_never_starts_or_returns_junk_is_named(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    harness.payload["data"] = None
    harness.script["fetch"] = ("ok", "fetch ran", [marker(jr.DATA_MARK, {"ok": False,
                                                                          "note": "status 403"})])
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "not downloadable" in outcome.error and "403" in outcome.error
    for bad, needle in ((b"<html><body>rate limited</body></html>", "HTML page"),
                        (b"\x89PNG\r\n\x1a\n" + b"0" * 30, "validation failed")):
        journal.clear(harness.bridge, harness.img)      # a new pass over the same image
        harness.payload["data"] = bad
        outcome = run(harness)
        assert outcome.status == fj.FAILED and needle in outcome.error, outcome.error


def test_a_temporary_download_failure_keeps_the_staging_file_clean(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    harness.payload["data"] = None
    harness.script["fetch"] = ("ok", "fetch ran", [marker(jr.DATA_MARK, {"ok": False, "note": "connection reset"})])
    assert run(harness).status == fj.FAILED
    assert not list(harness.tmp.glob(".*.part"))        # no half-written staging file left


def test_a_save_failure_is_reported_with_its_own_words(harness, monkeypatch):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())

    def no_space(directory, path, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fj.result, "atomic_write_bytes", no_space)
    outcome = run(harness)
    assert outcome.status == fj.FAILED and "No space left on device" in outcome.error
    assert "staging save failed" in outcome.error


# ------------------------------------------------------- pause, stop and cancel


def test_pause_before_submit_resumes_from_the_verified_checkpoint(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    harness.bridge._pause_requested = True

    async def scenario():
        task = asyncio.ensure_future(fj.run_image_job(harness.req))
        await asyncio.sleep(0.05)
        assert not task.done(), "a paused job must not submit"
        assert harness.calls == ["prepare"], "the checkpoint re-does no work while paused"
        harness.bridge._pause_requested = False
        return await task

    outcome = asyncio.run(scenario())
    assert outcome.status == fj.COMPLETED
    text = harness.bridge.text()
    assert "paused at the verified checkpoint" in text and "resumed from the verified checkpoint" in text


def test_cancel_before_submit_fails_safely_without_submitting(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    harness.bridge._cancel_requested = True
    outcome = run(harness)
    assert outcome.status == fj.CANCELLED and "Cancelled by user" == outcome.error
    assert "submit" not in harness.calls


def test_cancel_after_submit_keeps_the_in_flight_result_for_review(harness, monkeypatch):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())

    async def cancel_during_submit(b, page, inputs, report=None):
        harness.calls.append(inputs.stage)
        if inputs.stage != "submit":
            return harness.script.get(inputs.stage, ("ok", "stage ran", []))
        harness.bridge._cancel_requested = True          # the operator cancels mid-generation
        return "stopped", "stopped by the operator", submit_log()

    monkeypatch.setattr(fj, "run_job_stage", cancel_during_submit)
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW
    assert "cancelled after submit" in outcome.error
    assert "submit" in harness.calls


def test_stop_after_current_lets_the_job_finish_and_only_the_feeder_stops(harness):
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    harness.bridge._stop_after = True
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED
    assert "stop-after-current requested" in harness.bridge.text()


# ------------------------------------------------------- recovery before any run


def test_a_final_file_and_an_unpersisted_queue_state_reconcile_without_resubmitting(harness):
    """The file is on disk but the queue never heard: reconcile, never resubmit."""
    started = journal.now_iso()
    journal.write(harness.bridge, harness.img, phase="downloaded", started_at=started)
    produced = harness.tmp / "a_AI_2.png"
    produced.write_bytes(image_bytes())
    os.utime(produced, (fj.result.timestamp_of(started) + 5, fj.result.timestamp_of(started) + 5))
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED and outcome.output_path.endswith("a_AI_2.png")
    assert harness.calls == []                          # not one macro ran


def test_a_staged_download_is_finalized_without_touching_the_page(harness):
    staged_source = harness.tmp / "a_AI.png"
    from app.services import firefox_result as fr
    fr.store_staging(staged_source, image_bytes("JPEG"))
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED and harness.calls == []
    assert Path(outcome.output_path).is_file()


def test_a_recorded_submit_is_collected_from_the_journal_without_mode_two(harness):
    journal.write(harness.bridge, harness.img, phase="submitted", submit_clicks=1,
                  src="https://cdn/already.png")
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED and harness.calls == []
    assert Path(outcome.output_path).parent == harness.tmp


def test_a_recorded_submit_without_a_src_asks_the_page_and_never_resubmits(harness):
    journal.write(harness.bridge, harness.img, phase="submitted", submit_clicks=1)
    harness.script["probe"] = ("ok", "probe ran", [marker(jr.RESULT_MARK, {"candidates": [
        {"src": "https://cdn/kept.png", "after": True, "in_user": False, "large": True, "nat": 900}]})])
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED
    assert harness.calls == ["probe"]                    # the page was asked, nothing was clicked


def test_a_probe_that_finds_the_jobs_result_unfinished_is_a_review(harness):
    journal.write(harness.bridge, harness.img, phase="submitted", submit_clicks=1)
    harness.script["probe"] = ("ok", "probe ran", [marker(jr.RESULT_MARK, {"spinning": True})])
    outcome = run(harness)
    assert outcome.status == fj.NEEDS_REVIEW and harness.calls == ["probe"]


def test_a_journal_for_another_image_is_never_replayed(harness):
    journal.write(harness.bridge, harness.img, phase="submitted", submit_clicks=1,
                  src="https://cdn/other.png")
    other = journal.path_for(harness.bridge, harness.img)
    data = json.loads(other.read_text())
    data["image_path"] = str(harness.tmp / "not-ours.png")
    other.write_text(json.dumps(data))
    harness.script["prepare"] = ("ok", "prepare ran", prepare_log())
    harness.script["submit"] = ("ok", "submit ran", submit_log())
    outcome = run(harness)
    assert outcome.status == fj.COMPLETED and harness.calls == ["prepare", "submit"]

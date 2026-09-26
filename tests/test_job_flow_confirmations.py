"""The Chrome job end to end with step confirmations (2026-09-26, design D-3/D-4/D-5).

Owner report: "unable to finish job and save image after generation". Every
step is now confirmed on the page and the job ends with one ✔/✖ summary and
its final / recycle verdict.

RULE 8: the real runner, real ActionBlocks, real confirmations, tracker and
save; only the page answers, the controller and the click runner are fakes.
"""

from __future__ import annotations

import json

import pytest

from app.services.job_flow import confirm as jc
from app.services.job_flow import output as job_output
from app.services import single_job_runner as sjr
from app.utils.http_image import OutputError
from tests.characterization.harness import make_block
from tests.test_single_job_runner import instant_sleep, make_bridge, make_ctrl, make_ctx, make_img

pytestmark = pytest.mark.unit

CORE = ["OBSERVE_BASELINE", "CHECK_SECURITY", "ATTACH_IMAGE", "INSERT_PROMPT", "SUBMIT",
        "WAIT_OUTPUT", "DOWNLOAD", "VALIDATE", "SAVE", "ADVANCE"]
PROMPT = "p [JOB-ID: c1]"
CLEAN = {"composer_len": 0, "prompt_ok": False, "marker_in_composer": False, "previews": [],
         "bubble": False, "send_enabled": False, "generating": False, "errors": ""}
READY = dict(CLEAN, composer_len=len(PROMPT), prompt_ok=True, marker_in_composer=True,
             previews=[{"alt": "in.png", "blob": True}], send_enabled=True)
SENT = dict(CLEAN, bubble=True)


class Page:
    """Composer probes answer from `phases` (start → before click → after click); others: found."""

    def __init__(self, start=CLEAN, before=READY, after=SENT):
        self.phase = {"start": start, "before": before, "after": after}
        self.now = "start"
        self.composer_reads = []

    async def evaluate(self, js):
        if "__previews" in js:
            self.composer_reads.append(self.now)
            return self.phase[self.now]
        return json.dumps({"found": True, "rect": {"x": 1, "y": 1, "width": 5, "height": 5}})


def wire(monkeypatch, page, **ctrl_kw):
    """Clicks succeed; the page moves start → before (after attach) → after (after the click)."""
    clicks = []

    async def click(client, req, engine=None):
        clicks.append(req.selector)
        page.now = "after"
        return "ok"
    monkeypatch.setattr(sjr, "find_and_click", click)

    async def attach(path):
        page.now = "before"
        return True, "ok"
    ctrl = make_ctrl(attach_image=attach, **ctrl_kw)
    return ctrl, clicks


async def run(tmp_path, monkeypatch, page, stack=CORE, **ctrl_kw):
    instant_sleep(monkeypatch)
    ctrl, clicks = wire(monkeypatch, page, **ctrl_kw)
    bridge = make_bridge([make_block(b) for b in stack])
    img = make_img(tmp_path)
    img.attempt_count, img.selected = 1, True
    ctx = make_ctx(bridge, ctrl, page, img)
    failed, err, _src, _data = await sjr.run_blocks_for_image(ctx)
    return bridge, img, failed, err, clicks


def logs(bridge):
    return [m for m, _l in bridge._logs if isinstance(m, str)]


def summary(bridge):
    return next(m for m in reversed(logs(bridge)) if "🧭 Steps" in m)


async def test_happy_job_confirms_every_step_and_ends_final(tmp_path, monkeypatch):
    bridge, img, failed, err, clicks = await run(tmp_path, monkeypatch, Page())
    assert failed is False and err == "" and img.output_path
    joined = "\n".join(logs(bridge))
    for needle in ("▶ Job started — in.png", "✔ clean_start — empty composer", "✔ composer — image preview 1",
                   "✔ sent — new job started (JOB-ID message visible in the chat)",
                   "✔ output_detected — generation finished", "✔ saved_on_disk — in_AI.png"):
        assert needle in joined, needle
    assert summary(bridge).endswith("— COMPLETED → ■ final ✅ saved and confirmed on disk")
    assert "✔clean_start" in summary(bridge) and "✔sent" in summary(bridge)


async def test_prompt_left_in_the_composer_fails_as_not_delivered_and_recycles(tmp_path, monkeypatch):
    page = Page(after=READY)             # the click changed nothing
    bridge, img, failed, err, _ = await run(tmp_path, monkeypatch, page)
    assert failed is True and err.startswith("Submit not delivered — the prompt is still in the composer")
    assert not img.output_path
    line = summary(bridge)
    assert "✖submitted — FAILED at submitted" in line
    assert line.endswith("↻ recycle: back in the queue (attempt 1/∞) · nothing was sent — safe to retry")


async def test_already_sent_message_is_never_clicked_again(tmp_path, monkeypatch):
    calls = []

    async def submit():
        calls.append("controller")
        return True, "ok"
    page = Page(before=SENT)
    bridge, _img, failed, _err, clicks = await run(tmp_path, monkeypatch, page, submit=submit)
    assert failed is False and calls == []
    assert not [c for c in clicks if "send" in c.lower() or "submit" in c.lower()]
    assert ("SUBMIT", "success", "Already sent (JOB-ID message visible)") in bridge._events


async def test_dirty_start_that_cannot_be_cleaned_fails_before_anything_runs(tmp_path, monkeypatch):
    async def no_reset(reset_ctx):
        return False, "new-chat button not found"
    monkeypatch.setattr(jc, "reset_to_new_chat", no_reset)
    page = Page(start=dict(CLEAN, composer_len=9))
    bridge, _img, failed, err, _ = await run(tmp_path, monkeypatch, page)
    assert failed is True and err == "Page not clean at job start (9 chars of text) — nothing sent, safe to retry"
    assert bridge._events == []          # no block ran
    assert "FAILED at created" in summary(bridge)


async def test_save_failure_reason_reaches_the_job_error_and_the_log(tmp_path, monkeypatch):
    def full(source, data, spec):
        raise OutputError("save failed: [Errno 28] No space left on device")
    monkeypatch.setattr(job_output, "save_beside", full)
    bridge, img, failed, err, _ = await run(tmp_path, monkeypatch, Page())
    assert failed is True and err == "Save failed: save failed: [Errno 28] No space left on device"
    assert any("❌ Save failed: save failed: [Errno 28]" in m for m in logs(bridge))
    assert "image generated but not saved" in summary(bridge)


async def test_a_short_write_is_caught_by_the_disk_confirmation(tmp_path, monkeypatch):
    def short(source, data, spec):
        out = tmp_path / "in_AI.png"
        out.write_bytes(data[:10])
        return out
    monkeypatch.setattr(job_output, "save_beside", short)
    _bridge, img, failed, err, _ = await run(tmp_path, monkeypatch, Page())
    assert failed is True and err.startswith("Save not confirmed: 10/") and not img.output_path


async def test_unreadable_page_keeps_the_old_behaviour(tmp_path, monkeypatch):
    """RULE 9: probes that answer nothing useful fail open — the stack runs as before."""
    page = Page(start={}, before={}, after={})
    page.evaluate = _found_only
    bridge, img, failed, _err, _ = await run(tmp_path, monkeypatch, page)
    assert failed is False and img.output_path
    assert any("⚠ clean_start — composer not readable" in m for m in logs(bridge))


async def _found_only(js):
    return json.dumps({"found": True, "rect": {"x": 1, "y": 1, "width": 5, "height": 5}})

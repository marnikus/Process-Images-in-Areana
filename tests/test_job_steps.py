"""Chrome job step tracker — milestones, summary, final / recycle verdict (2026-09-26).

docs/archive/2026-09-26-chrome-job-save-and-confirmations/design.md D-4.
RULE 8: the real tracker + the real retry-cap reader; only the bridge is faked.
"""

from types import SimpleNamespace

import pytest

from app.services.job_flow import steps as js

pytestmark = pytest.mark.unit


def make_ctx(attempts=1, cap=3, selected=True):
    logs = []
    retries = {"max_attempts": cap}
    bridge = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(retries=retries)),
                             _log=lambda m, l="info": logs.append((m, l)), logs=logs)
    img = SimpleNamespace(relative_path="dir/cat.png", attempt_count=attempts, selected=selected)
    return SimpleNamespace(bridge=bridge, img=img, corr_id="c1", tab_id="TAB123456789", steps=None)


def test_start_logs_image_tab_and_attempt():
    ctx = make_ctx(attempts=2, cap=3)
    steps = js.start_steps(ctx)
    assert ctx.steps is steps and steps.trail == [("created", True)]
    assert ctx.bridge.logs[-1] == ("[c1] ▶ Job started — cat.png · tab TAB12345 · attempt 2/3", "info")


def test_milestones_move_forward_only_and_helpers_are_ignored():
    ctx = make_ctx()
    js.start_steps(ctx)
    for block in ("OBSERVE_BASELINE", "HIGHLIGHT", "ATTACH_IMAGE", "VERIFY_ATTACHMENT", "INSERT_PROMPT"):
        js.track_block(ctx, block, None)
    assert ctx.steps.reached == "prompt_inserted"
    assert [n for n, _ in ctx.steps.trail] == ["created", "baseline_captured", "attachment_verified",
                                              "prompt_inserted"]
    assert {"HIGHLIGHT", "VERIFY_ATTACHMENT"} <= ctx.steps.done_blocks
    assert any("✔ attachment_verified — image attached" in m for m, _ in ctx.bridge.logs)


def test_failure_is_marked_and_named():
    ctx = make_ctx()
    js.start_steps(ctx)
    js.track_block(ctx, "SAVE", "Save failed: disk full")
    js.track_block(ctx, "CUSTOM_FIND", "not found")
    assert ctx.steps.trail[-2:] == [("saving", False), ("custom_find", False)]
    assert ctx.steps.failed_at == "custom_find"
    assert ("[c1] ✖ saving — Save failed: disk full", "warn") in ctx.bridge.logs


@pytest.mark.parametrize("reached,needle", [
    ("created", "nothing was sent"),
    ("prompt_verified", "nothing was sent"),
    ("submitted", "sent, but no finished image"),
    ("output_detected", "generated but not saved"),
    ("saving", "generated but not saved"),
])
def test_stage_note_by_the_furthest_step(reached, needle):
    assert needle in js.stage_note(reached)


@pytest.mark.parametrize("out,needle", [
    (js.Outcome(failed=False), "■ final ✅ saved"),
    (js.Outcome(failed=True, cancelled=True), "■ stopped by the operator"),
    (js.Outcome(failed=True, attempts=1, cap=3), "↻ recycle: back in the queue (attempt 1/3)"),
    (js.Outcome(failed=True, attempts=9, cap=0), "↻ recycle: back in the queue (attempt 9/∞)"),
    (js.Outcome(failed=True, attempts=3, cap=3), "■ final: no attempts left (3/3)"),
    (js.Outcome(failed=True, attempts=1, cap=3, selected=False), "■ final: no attempts left"),
])
def test_verdict_follows_the_live_loop_retry_rule(out, needle):
    assert needle in js.verdict("submitted", out)


def test_finish_writes_one_summary_line_for_a_saved_job():
    ctx = make_ctx()
    js.start_steps(ctx)
    for block in ("OBSERVE_BASELINE", "ATTACH_IMAGE", "SUBMIT", "WAIT_OUTPUT", "DOWNLOAD", "VALIDATE", "SAVE"):
        js.track_block(ctx, block, None)
    line = js.finish_steps(ctx, False, "", False)
    assert line.startswith("🧭 Steps ✔created ✔baseline_captured ✔attachment_verified ✔submitted "
                           "✔output_detected ✔downloading ✔validating ✔saving ✔completed — COMPLETED")
    assert ctx.bridge.logs[-1] == (f"[c1] {line}", "success")


def test_finish_of_a_failed_job_says_where_and_what_next():
    ctx = make_ctx(attempts=3, cap=3)
    js.start_steps(ctx)
    js.track_block(ctx, "SUBMIT", None)
    js.track_block(ctx, "WAIT_OUTPUT", "Wait failed: Timeout after 180000ms")
    line = js.finish_steps(ctx, True, "Wait failed: Timeout after 180000ms", False)
    assert "✖output_detected — FAILED at output_detected: Wait failed: Timeout" in line
    assert line.endswith("■ final: no attempts left (3/3) · sent, but no finished image — "
                         "a retry sends a new job — Retry runs it again")
    assert ctx.bridge.logs[-1][1] == "error"
    ctx2 = make_ctx(attempts=1, cap=3)
    js.start_steps(ctx2)
    assert ctx2.bridge.logs and js.finish_steps(ctx2, True, "x", False).count("↻") == 1
    assert ctx2.bridge.logs[-1][1] == "warn"


def test_tracker_survives_a_broken_logger_and_a_bare_ctx():
    bare = SimpleNamespace(corr_id="c9")          # no bridge: the tracker still works
    js.track_block(bare, "SAVE", None)
    assert bare.steps.reached == "saving"
    boom = SimpleNamespace(bridge=SimpleNamespace(_log=lambda *a: 1 / 0), corr_id="c2")
    js.steps_of(boom).confirm("composer", "ok")  # the ZeroDivisionError is swallowed
    assert boom.steps.trail == [("composer", True)]

"""I-78 · a poll the page did not answer is no evidence — owner log 2026-09-28 08:29–08:32.

The job's output wait read `page_unresponsive` (no `spinning` key) as "✅ Spinner
gone"; the resubmit policy counted the same unanswered polls as a dead
generation and resubmitted into a socket that answered nothing ("Resubmit
re-attach: Failed to get document root", "Resubmit Send: Not connected"); and
the wait timed out on an unanswered check without ever looking for the image
the Watcher had already seen finish. The Watcher has held on unanswered ticks
since I-71; these tests pin the same rule on the job's side.

Real `wait_for_new_output_with_spec` loop and real `ResumePolicy` (RULE 8);
only the page answers are scripted.
"""

import asyncio

import pytest

import app.services.captcha.recovery as recovery_mod
from app.browser.output_state import unanswered
from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec
from app.services.captcha.recovery import RESUME_GRACE_SEC, arm_resume, maybe_resume, note_settle

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

SPINNING = {"ready": False, "reason": "generating_spinner_visible", "spinning": True,
            "spinDetails": [{"label": "Max"}]}
FROZEN = {"ready": False, "reason": "page_unresponsive",
          "detail": "page not answering (TimeoutError: CDP command Runtime.evaluate timed out after 30.0s)"}
NO_RESULT = {"ready": False, "reason": "no_result", "detail": "CDP not connected"}
DEAD = {"ready": False, "reason": "generating_no_new_yet", "spinning": False, "allNew": 0}
READY = {"ready": True, "reason": "ok", "src": "blob:new-image"}


def scripted(*answers):
    """check_fn answering `answers` in order (the last one repeats); counts its polls."""
    polls = {"n": 0}

    async def check_fn():
        polls["n"] += 1
        return dict(answers[min(polls["n"], len(answers)) - 1])

    check_fn.polls = polls
    return check_fn


async def run(check_fn, timeout=5.0):
    lines = []
    spec = WaitSpec(timeout=timeout, poll_interval=0.01)
    result = await asyncio.wait_for(
        wait_for_new_output_with_spec(check_fn, lines.append, None, spec), 15)
    return result, lines


# --- the predicate ---------------------------------------------------------

@pytest.mark.parametrize("diag", [FROZEN, NO_RESULT])
async def test_unanswered_names_the_probes_that_got_no_answer(diag):
    assert unanswered(diag)


@pytest.mark.parametrize("diag", [SPINNING, DEAD, READY, {}, None])
async def test_an_answer_is_not_unanswered(diag):
    assert not unanswered(diag)


# --- the wait loop: 08:30:58 "page_unresponsive" → "✅ Spinner gone" ---------

async def test_unanswered_poll_does_not_read_as_spinner_gone():
    check = scripted(SPINNING, FROZEN, FROZEN, SPINNING, READY)
    result, lines = await run(check)
    assert result.get("ready") and result.get("src") == "blob:new-image"
    assert not any("Spinner gone" in line for line in lines), lines
    assert sum("spinner visible" in line for line in lines) == 1, lines   # the state was kept


async def test_answered_spinner_loss_still_reads_as_spinner_gone():
    _, lines = await run(scripted(SPINNING, DEAD, READY))
    assert any("Spinner gone" in line for line in lines), lines


# --- the deadline: 08:32:08 failed on an unanswered check, never looked -----

async def test_deadline_on_an_unanswered_check_takes_one_last_look():
    async def slow_frozen():            # the 30 s probe timeout, scaled down
        await asyncio.sleep(0.3)
        return dict(FROZEN)
    answers = iter([slow_frozen, None])

    async def check_fn():
        step = next(answers, None)
        return await step() if step else dict(READY)

    result, lines = await run(check_fn, timeout=0.2)
    assert result.get("ready") and result.get("src") == "blob:new-image", result
    assert any("last look" in line for line in lines), lines


async def test_the_last_look_is_one_poll_not_a_new_wait():
    check = scripted(FROZEN)            # the page never answers again
    result, lines = await run(check, timeout=0.05)
    assert result["reason"] == "timeout" and result["last"]["reason"] == "page_unresponsive"
    assert sum("last look" in line for line in lines) == 1, lines


async def test_an_answered_last_check_times_out_without_a_last_look():
    result, lines = await run(scripted(SPINNING), timeout=0.05)
    assert result["reason"] == "timeout"
    assert not any("last look" in line for line in lines), lines


# --- the resubmit policy: 08:31:32 "Generation stalled" on no answers --------

class Ctrl:
    def __init__(self):
        self.calls = []

    async def insert_prompt(self, prompt):
        self.calls.append("insert")
        return True, "ok"

    async def submit(self):
        self.calls.append("submit")
        return True, "ok"


def armed(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(recovery_mod.time, "monotonic", lambda: clock["t"])
    ctrl = Ctrl()
    arm_resume(ctrl, "[JOB-ID: abc] icon", report=lambda *_a: None)
    return ctrl, clock


async def polls(ctrl, clock, diag, seconds, step=5):
    for _ in range(int(seconds // step)):
        clock["t"] += step
        await maybe_resume(ctrl, dict(diag))


async def test_unanswered_polls_after_the_spinner_never_resubmit(monkeypatch):
    ctrl, clock = armed(monkeypatch)
    await maybe_resume(ctrl, dict(SPINNING))
    await polls(ctrl, clock, FROZEN, 60)
    await polls(ctrl, clock, NO_RESULT, 30)
    assert ctrl.calls == []


async def test_a_dead_window_restarts_at_the_next_answered_poll(monkeypatch):
    ctrl, clock = armed(monkeypatch)
    await maybe_resume(ctrl, dict(SPINNING))
    await polls(ctrl, clock, DEAD, RESUME_GRACE_SEC - 5)     # almost due …
    await polls(ctrl, clock, FROZEN, 30)                      # … then no answers
    await polls(ctrl, clock, DEAD, RESUME_GRACE_SEC - 5)      # a fresh, unfinished window
    assert ctrl.calls == []
    await polls(ctrl, clock, DEAD, 10)                        # the answered window matures
    assert ctrl.calls == ["insert", "submit"]


async def test_the_settle_window_restarts_at_the_next_answered_poll(monkeypatch):
    ctrl, clock = armed(monkeypatch)
    note_settle(ctrl)
    await polls(ctrl, clock, FROZEN, RESUME_GRACE_SEC + 30)
    await polls(ctrl, clock, DEAD, RESUME_GRACE_SEC - 5)
    assert ctrl.calls == []
    await polls(ctrl, clock, DEAD, 10)
    assert ctrl.calls == ["insert", "submit"]

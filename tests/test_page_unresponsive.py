"""A page that stops answering — told in words, a 3 s ping, never a hang (I-71, 2026-09-27).

Owner log: Submit 17:24:46 → captcha solved 17:24:55 → the Watcher said "generation
finished" at 17:25:43 and resumed 30 s later → `🔍 Output check: no_result` at
17:27:15 → `Timeout after 120000ms — last check: no_result` at 17:28:17 → the New
Chat reset hung at `FIND phase`. Every `Runtime.evaluate` was timing out (30 s):
one output poll cost ~90 s (gate + check + error scan), the timeout text hid the
reason, the Watcher read "no answer" as "spinner gone", and each New Chat
candidate burned another 30 s.
"""
import time

import pytest

from app.browser import new_chat as nc
from app.browser import output_wait as ow
from app.browser import page_recovery as pr
from app.browser.cdp_arena import output as out
from app.browser.cdp_arena.state import is_generating
from app.services.watcher import WatcherService
from app.services.watcher_config import WatcherConfig
from tests.test_new_chat import FakeCtrl, FakeEngine, make_ctx

pytestmark = pytest.mark.unit

TIMED_OUT = "TimeoutError: CDP command Runtime.evaluate timed out after 30s"
FROZEN = f"page not answering ({TIMED_OUT}; nothing received yet)"   # fakes receive nothing


class FrozenPage:
    """CDP boundary of a page whose main thread is stuck: evaluates time out, the
    browser-side commands (history) still answer, a ping answers only when told."""

    def __init__(self, answers_ping=False, timed_out=False):
        self.answers_ping, self.calls, self.eval_timeouts = answers_ping, [], []
        self.last_error, self.last_error_kind = (TIMED_OUT, "transport") if timed_out else ("", "")

    async def evaluate(self, expr, await_promise=True, timeout=30.0):
        self.calls.append("evaluate")
        self.eval_timeouts.append(timeout)
        self.last_error, self.last_error_kind = TIMED_OUT, "transport"
        return None

    async def send(self, method, params=None, timeout=30):
        self.calls.append(f"{method}@{timeout:g}")
        if method == "Page.getNavigationHistory":
            return {"id": 1, "result": {"currentIndex": 0, "entries": [{"url": "https://arena.ai/c/abc"}]}}
        if method == "Runtime.evaluate" and self.answers_ping:
            return {"result": {"result": {"type": "number", "value": 1}}}
        raise TimeoutError(f"CDP command {method} timed out after {timeout:g}s")


# ── page_recovery: the record, the ping ─────────────────────────────────────

@pytest.mark.parametrize("kind, text, frozen", [
    ("transport", TIMED_OUT, True),
    ("transport", "ConnectionError: CDP not connected", False),   # a dead socket is not a stuck page
    ("protocol", "Execution context was destroyed.", False),
    ("js", "TypeError: x is null", False),
    ("", "", False),
])
def test_only_a_timed_out_evaluate_marks_the_page_unresponsive(kind, text, frozen):
    page = FrozenPage()
    page.last_error_kind, page.last_error = kind, text
    assert pr.page_unresponsive(page) is frozen


async def test_an_answered_ping_clears_the_record():
    page = FrozenPage(answers_ping=True, timed_out=True)
    assert await pr.still_frozen(page) is False
    assert page.calls == ["Runtime.evaluate@3"] and page.last_error_kind == ""


async def test_an_unanswered_ping_keeps_the_record():
    page = FrozenPage(timed_out=True)
    assert await pr.still_frozen(page) is True
    assert pr.unresponsive_text(page) == FROZEN


async def test_a_page_that_never_timed_out_is_not_pinged():
    page = FrozenPage()
    assert await pr.still_frozen(page) is False and page.calls == []


# ── the output wait ─────────────────────────────────────────────────────────

async def test_a_timed_out_check_is_page_unresponsive_and_skips_the_30s_error_scan():
    page = FrozenPage()
    diag = await out._poll_output_diag(page, out.PollContext(), None)
    assert diag == {"ready": False, "reason": "page_unresponsive",
                    "detail": FROZEN}
    assert page.calls == ["evaluate"]                 # was: check + error scan (+30 s)
    assert page.eval_timeouts == [5.0]                # I-73: a page check waits 5 s, not 30 s


async def test_a_check_that_threw_is_no_result_with_its_reason_and_still_scans():
    class Throws(FrozenPage):
        async def evaluate(self, expr, await_promise=True, timeout=30.0):
            self.calls.append("evaluate")
            self.last_error, self.last_error_kind = "TypeError: boom", "js"
            return None
    page = Throws()
    diag = await out._poll_output_diag(page, out.PollContext(), None)
    assert diag == {"ready": False, "reason": "no_result", "detail": "TypeError: boom"}
    assert page.calls == ["evaluate", "evaluate"]     # check + error scan


async def test_a_frozen_wait_pings_tells_once_and_times_out_with_the_reason(monkeypatch):
    async def no_sleep(_s):
        return None
    monkeypatch.setattr(ow.asyncio, "sleep", no_sleep)
    page, said = FrozenPage(), []
    started = time.monotonic()
    status, info = await out.wait_for_new_output(page, out.WaitSpec(timeout_ms=200, log_cb=said.append))
    assert status == "failed" and time.monotonic() - started < 5
    assert info["error"] == (f"Timeout after 200ms — last check: page_unresponsive "
                             f"({FROZEN})")
    assert page.calls.count("evaluate") <= 2          # the error-corpus scan + one check — then pings
    assert set(page.calls[2:]) <= {"Runtime.evaluate@3"}
    assert info["last_baseline"] == {}                # no 30 s baseline on a page that is not answering
    assert said.count(f"🔍 Output check: page_unresponsive — {FROZEN}") == 1


def test_the_log_line_carries_the_detail():
    said = []
    ow.note_reason({"reason": "no_result", "detail": "TypeError: boom"}, said.append)
    assert said == ["🔍 Output check: no_result — TypeError: boom"]


# ── New Chat ────────────────────────────────────────────────────────────────

async def test_new_chat_on_a_frozen_page_skips_the_find_probes_and_says_why(monkeypatch):
    async def never(*_a, **_k):
        raise AssertionError("FIND must not run on a page that is not answering")
    monkeypatch.setattr(nc, "find_and_click", never)
    page, engine = FrozenPage(timed_out=True), FakeEngine()
    started = time.monotonic()
    ok, reason = await nc.reset_to_new_chat(make_ctx(ctrl=FakeCtrl(), client=page, engine=engine, timeout=1))
    assert ok is False and time.monotonic() - started < 5
    assert reason.startswith(f"{FROZEN}; direct open: navigation failed")
    assert any("New Chat did not work (page not answering" in m for m, _ in engine.records)
    assert engine.records[-1][1] == "error"


async def test_readiness_on_a_frozen_page_costs_a_ping_not_a_probe():
    page = FrozenPage(timed_out=True)
    ok, note = await nc._check_ready(make_ctx(ctrl=FakeCtrl(), client=page))
    assert (ok, note) == (False, FROZEN)
    assert page.calls == ["Runtime.evaluate@3"]


# ── the Watcher ─────────────────────────────────────────────────────────────

class SilentPage:
    """The Watcher's page: spinner first, then no answer at all."""

    def __init__(self):
        self.answering, self.hides = True, 0
        self.last_error, self.last_error_kind = "", ""

    async def is_security_dialog_visible(self):
        return False

    async def is_generating(self):
        if self.answering:
            return True, {"details": [], "jobs": ["a1"]}
        return False, {"unanswered": True, "error": TIMED_OUT}

    async def show_watcher_overlay(self, msg, kind=None, timeout_sec=None, owner_key=""):
        return None

    async def hide_watcher_overlay(self, owner_key=""):
        self.hides += 1


class Runner:
    def __init__(self):
        self.paused = self.resumed = 0

    def pause_run(self):
        self.paused += 1

    def resume_run(self):
        self.resumed += 1


def _watcher(page, runner, logs, timeout=180):
    svc = WatcherService(config=WatcherConfig(enabled=True, generation_timeout_sec=timeout),
                         cdp_controller_getter=lambda: page, job_runner_getter=lambda: runner)
    svc.set_logger(lambda msg, level="info": logs.append((level, msg)))
    return svc


async def test_the_watcher_holds_a_generation_wait_while_the_page_is_silent():
    page, runner, logs = SilentPage(), Runner(), []
    svc = _watcher(page, runner, logs)
    await svc.check_once()
    page.answering = False
    for _ in range(4):
        state = await svc.check_once()
    assert state["waiting_kind"] == "generation"                  # was: "generation finished"
    assert (runner.resumed, page.hides) == (0, 0)
    assert not [m for _l, m in logs if "finished after" in m]
    assert len([m for _l, m in logs if "page is not answering" in m]) == 1


async def test_a_silent_page_still_lets_the_generation_timeout_end_the_wait():
    page, runner, logs = SilentPage(), Runner(), []
    svc = _watcher(page, runner, logs)
    await svc.check_once()
    page.answering = False
    svc._loop._pages._pages["primary"].state.waiting_since = time.time() - 181
    state = await svc.check_once()
    assert state["waiting_kind"] is None and runner.resumed == 1
    assert len([m for _l, m in logs if "Generation timeout" in m]) == 1


async def test_the_silence_line_is_told_again_after_the_page_came_back():
    page, runner, logs = SilentPage(), Runner(), []
    svc = _watcher(page, runner, logs)
    for answering in (False, False, True, False):
        page.answering = answering
        await svc.check_once()
    assert len([m for _l, m in logs if "page is not answering" in m]) == 2


async def test_is_generating_marks_an_unanswered_probe():
    page = FrozenPage()
    gen, details = await is_generating(page)
    assert gen is False and details == {"unanswered": True, "error": TIMED_OUT}


async def test_the_watcher_probe_and_the_error_scan_are_page_checks_of_5s():
    from app.browser.cdp_arena.state import is_generating, scan_page_errors
    page = FrozenPage()
    await is_generating(page)
    await scan_page_errors(page)
    assert page.eval_timeouts == [5.0, 5.0]           # I-73: was the 30 s command default

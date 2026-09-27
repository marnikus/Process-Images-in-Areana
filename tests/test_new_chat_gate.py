"""A job starts only on a verified new chat; otherwise New Chat first, then verify again (I-74).

Owner request 2026-09-27: "the app does not check if the new job goes on a new chat page or
not. Verify if the web page is a new chat! If not, start a new chat first." A job runs on
whatever the tab shows — a failed post-job reset or a chat the user opened sent the next
image into an old conversation.
"""
from types import SimpleNamespace

import pytest

from app.services import new_chat_gate as gate

pytestmark = pytest.mark.unit

FRESH = {"path": "/image/direct", "messages": 0, "outputs": 0, "attachments": 0, "composer": 0}
OLD_CHAT = {**FRESH, "path": "/c/01a0e496", "messages": 1, "outputs": 1}


class Bridge:
    def __init__(self, cancel=False):
        self.lines, self._cancel_requested = [], cancel

    def _log(self, msg, level="info"):
        self.lines.append((msg, level))


class Page:
    """The tab: answers the chat-page probe from a script of states."""

    def __init__(self, *states):
        self.states, self.last_error, self.last_error_kind = list(states), "", ""

    async def evaluate(self, js, await_promise=True, timeout=30.0):
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]


@pytest.fixture
def resets(monkeypatch):
    calls = []

    async def fake_reset(ctx):
        calls.append(ctx)
        return (True, "new chat ready") if not calls[-1].client.states[0].get("broken") else (False, "button not found")
    monkeypatch.setattr(gate, "reset_to_new_chat", fake_reset)
    return calls


async def test_a_new_chat_starts_the_job_without_a_reset(resets):
    bridge = Bridge()
    assert await gate.ensure_new_chat(bridge, Page(FRESH), ctrl=object()) == (True, "")
    assert resets == []
    assert bridge.lines == [("🆕 New chat verified — starting the job", "info")]


async def test_an_old_chat_gets_a_new_chat_first_then_is_verified_again(resets):
    bridge = Bridge()
    page = Page(OLD_CHAT, FRESH)
    assert await gate.ensure_new_chat(bridge, page, ctrl="ctrl") == (True, "")
    assert len(resets) == 1 and resets[0].ctrl == "ctrl" and resets[0].client is page
    assert resets[0].purpose == "before the job"
    assert bridge.lines == [
        ("🆕 Not a new chat page (a started chat (/c/01a0e496), 1 message(s) on the page, "
         "1 generated image(s) on the page) — starting a new chat first", "warn"),
        ("🆕 New chat verified after the reset — starting the job", "success")]


async def test_still_not_new_after_the_reset_fails_the_job_and_says_why(resets):
    bridge = Bridge()
    ok, why = await gate.ensure_new_chat(bridge, Page(OLD_CHAT), ctrl=None)
    assert ok is False
    assert why == ("Not a new chat page (a started chat (/c/01a0e496), 1 message(s) on the page, "
                   "1 generated image(s) on the page) — New Chat did not help")
    assert bridge.lines[-1] == (f"❌ {why} — the job is not started", "error")


async def test_a_failed_reset_is_named_in_the_reason(resets):
    broken = {**OLD_CHAT, "broken": True}
    ok, why = await gate.ensure_new_chat(Bridge(), Page(broken), ctrl=None)
    assert ok is False and why.endswith("— New Chat failed: button not found")


async def test_a_page_that_does_not_say_is_reset_too(resets):
    page = Page(None, FRESH)
    page.last_error = "TimeoutError: CDP command Runtime.evaluate timed out after 5.0s"
    bridge = Bridge()
    assert await gate.ensure_new_chat(bridge, page, ctrl=None) == (True, "")
    assert len(resets) == 1
    assert bridge.lines[0][0].startswith("🆕 Not a new chat page (the page did not say (TimeoutError")


async def test_a_reset_that_raises_is_a_failed_reset_not_a_crash(monkeypatch):
    async def boom(_ctx):
        raise RuntimeError("socket gone")
    monkeypatch.setattr(gate, "reset_to_new_chat", boom)
    ok, why = await gate.ensure_new_chat(Bridge(), Page(OLD_CHAT), ctrl=None)
    assert ok is False and why.endswith("— New Chat failed: socket gone")


async def test_the_reset_honours_a_cancelled_run(resets):
    bridge = Bridge(cancel=True)
    await gate.ensure_new_chat(bridge, Page(OLD_CHAT, FRESH), ctrl=None)
    assert resets[0].cancel_check() is True


# ── both job paths ask the gate before anything touches the page ──

async def test_the_sequential_job_fails_without_running_blocks_when_the_gate_says_no(monkeypatch):
    from app.services import batch_orchestrator as bo
    ran = []

    async def no(_bridge, _client, _ctrl):
        return False, "Not a new chat page (x) — New Chat did not help"

    async def blocks(_ctx):
        ran.append(1)
        return False, "", None, None
    monkeypatch.setattr(bo, "ensure_new_chat", no)
    monkeypatch.setattr(bo, "run_blocks_for_image", blocks)
    monkeypatch.setattr(bo, "build_job_ids", lambda ctx, img, row: ("C1", "J1", "prompt"))
    ctx = SimpleNamespace(bridge=SimpleNamespace(cdp="client"), ctrl="ctrl", tab_id="t", urls=[])
    res = await bo._execute_image(ctx, SimpleNamespace(relative_path="a.png"), None)
    assert (res.failed, res.error, res.job_id) == (True, "Not a new chat page (x) — New Chat did not help", "J1")
    assert ran == []


async def test_the_parallel_job_asks_the_gate_before_the_baseline(monkeypatch):
    from app.services import multi_page_dispatcher as mpd
    order = []

    async def prep(_bridge, _img, _urls, _tab):
        return "row", "C1", "J1", "prompt"

    async def no(_bridge, client, _ctrl):
        order.append(("gate", client))
        return False, "Not a new chat page (x) — New Chat did not help"

    async def baseline(_ctrl):
        order.append("baseline")
        return {}
    monkeypatch.setattr(mpd, "prepare_image_for_job", prep)
    monkeypatch.setattr(mpd, "ensure_new_chat", no)
    monkeypatch.setattr(mpd, "capture_baseline", baseline)
    bridge = SimpleNamespace(job_started=SimpleNamespace(emit=lambda *a: None))
    ctx = mpd.PageJobCtx(bridge=bridge, pool=None, img=SimpleNamespace(absolute_path="a"), urls=[],
                         tab_id="t", ctrl="ctrl", client="pool-client")
    assert await mpd._run_image_job(ctx) == ("row", "C1", "J1", True,
                                             "Not a new chat page (x) — New Chat did not help")
    assert order == [("gate", "pool-client")]

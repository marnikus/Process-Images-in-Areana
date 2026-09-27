"""Page restart after a failed New Chat reset (2026-09-27 D-4).

RULE 8: the real page_restart / reset_to_new_chat orchestration runs; only the
CDP boundary is a scripted fake. The fakes speak the transport's real reply
shape: the raw message `{"id", "result": {...}}` or `{"id", "error": {...}}`.
The navigate/dialog/terminate order was proven in real Chromium first
(design §5).
"""

import asyncio

import pytest

from app.browser import new_chat as nc
from app.browser import page_restart as pr

TAB = "https://arena.ai/c/0199-abc?mode=direct"


class FakeCDP:
    """Scripted `send`: per-method replies (callables may sleep or raise)."""

    def __init__(self, url=TAB, nav=None):
        self.sent = []
        self.url = url
        self.nav = list(nav or [{"id": 2, "result": {"frameId": "F"}}])

    async def send(self, method, params=None, timeout=30):
        self.sent.append(method)
        if method == "Target.getTargetInfo":
            if isinstance(self.url, Exception):
                raise self.url
            return {"id": 1, "result": {"targetInfo": {"url": self.url, "type": "page"}}}
        if method == "Page.navigate":
            step = self.nav.pop(0) if len(self.nav) > 1 else self.nav[0]
            return await step() if callable(step) else step
        return {"id": 9, "result": {}}


@pytest.mark.unit
def test_new_chat_url_is_origin_plus_the_new_chat_href():
    assert pr.new_chat_url(TAB) == "https://arena.ai/image/direct"
    assert pr.new_chat_url("http://127.0.0.1:8801/x.html") == "http://127.0.0.1:8801/image/direct"
    for bad in ("", "about:blank", "chrome://newtab/", "file:///C:/x.html"):
        assert pr.new_chat_url(bad) == ""


@pytest.mark.unit
async def test_restart_navigates_to_the_tabs_new_chat_page():
    cdp = FakeCDP()
    ok, info = await pr.restart_to_new_chat(cdp)
    assert (ok, info) == (True, "https://arena.ai/image/direct")
    assert cdp.sent == ["Target.getTargetInfo", "Page.navigate"]


@pytest.mark.unit
async def test_unknown_tab_address_is_an_honest_failure():
    for url in (RuntimeError("socket closed"), "about:blank"):
        ok, why = await pr.restart_to_new_chat(FakeCDP(url=url))
        assert not ok and "address is unknown" in why


@pytest.mark.unit
async def test_navigate_error_text_retries_after_terminating_a_stuck_script():
    cdp = FakeCDP(nav=[{"id": 2, "result": {"errorText": "net::ERR_ABORTED"}},
                       {"id": 3, "result": {"frameId": "F"}}])
    ok, _ = await pr.restart_to_new_chat(cdp)
    assert ok
    assert cdp.sent == ["Target.getTargetInfo", "Page.navigate", "Runtime.terminateExecution", "Page.navigate"]


@pytest.mark.unit
async def test_cdp_error_reply_counts_as_failure_with_its_message():
    err = {"id": 2, "error": {"code": -32000, "message": "Cannot navigate to invalid URL"}}
    ok, why = await pr.restart_to_new_chat(FakeCDP(nav=[err]))
    assert not ok and "Cannot navigate to invalid URL" in why and why.startswith("https://arena.ai/image/direct")


@pytest.mark.unit
async def test_a_navigate_held_by_a_leave_page_dialog_gets_the_dialog_accepted(monkeypatch):
    monkeypatch.setattr(pr, "DIALOG_GRACE_S", 0.01)

    async def held():
        await asyncio.sleep(0.05)   # the dialog holds the navigate open …
        return {"id": 2, "result": {"frameId": "F"}}

    cdp = FakeCDP(nav=[held])
    ok, _ = await pr.restart_to_new_chat(cdp)
    assert ok
    assert cdp.sent == ["Target.getTargetInfo", "Page.navigate", "Page.handleJavaScriptDialog"]


@pytest.mark.unit
async def test_navigate_exceptions_become_reasons():
    async def boom():
        raise TimeoutError("CDP command Page.navigate timed out after 15.0s")

    ok, why = await pr.restart_to_new_chat(FakeCDP(nav=[boom]))
    assert not ok and "TimeoutError" in why and "timed out" in why


# ── reset_to_new_chat: click stage → restart stage ─────────────────────


class RestartClient(FakeCDP):
    """new_chat's evaluate probes (page loaded, composer empty) + restart sends."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.loaded_after_restart = True

    async def evaluate(self, expr, await_promise=True):
        restarted = "Page.navigate" in self.sent
        loaded = restarted and self.loaded_after_restart
        if "readyState" in expr:
            return {"complete": loaded, "readyState": "complete" if loaded else "loading", "hasTextarea": True}
        return {"empty": True, "len": 0}


class Ready:
    async def is_page_ready(self):
        return True, []


class Engine:
    def __init__(self):
        self.lines = []

    def report(self, message, level="info"):
        self.lines.append((level, message))


def _ctx(client, timeout=0.3, cancel=None):
    return nc.ResetCtx(ctrl=Ready(), client=client, engine=Engine(), timeout_sec=timeout, cancel_check=cancel)


async def _no_button(client, req, engine=None):
    return "not_found"


@pytest.mark.unit
async def test_failed_click_restarts_the_page_and_proves_a_clean_composer(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _no_button)
    ctx = _ctx(RestartClient())
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert ok and reason == "after page restart: new chat ready"
    text = [m for _, m in ctx.engine.lines]
    assert any("New Chat did not open (new-chat button not found) — restarting the page" in m for m in text)
    assert any("Page restarted at https://arena.ai/image/direct" in m for m in text)
    assert text[-1].startswith("↩ ✔ New chat open")


@pytest.mark.unit
async def test_failed_restart_reports_both_reasons(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _no_button)
    ctx = _ctx(RestartClient(url="about:blank"))
    ok, reason = await nc.reset_to_new_chat(ctx)
    assert not ok
    assert reason == "new-chat button not found; page restart failed: the tab's address is unknown"
    assert ctx.engine.lines[-1] == ("error", f"↩ New-chat reset failed: {reason}")


@pytest.mark.unit
async def test_restart_whose_page_never_loads_is_a_failure(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _no_button)
    client = RestartClient()
    client.loaded_after_restart = False
    ok, reason = await nc.reset_to_new_chat(_ctx(client, timeout=0.2))
    assert not ok and reason.startswith("new-chat button not found; after page restart: timeout waiting")


@pytest.mark.unit
async def test_a_silent_click_stage_is_cut_at_its_budget_then_restarted(monkeypatch):
    async def hangs(client, req, engine=None):
        await asyncio.sleep(30)   # the page stopped answering mid-FIND

    monkeypatch.setattr(nc, "find_and_click", hangs)
    monkeypatch.setattr(nc, "STAGE_SLACK_S", 0.05)
    ctx = _ctx(RestartClient(), timeout=0.05)
    ok, reason = await asyncio.wait_for(nc.reset_to_new_chat(ctx), timeout=5)
    assert ok and reason == "after page restart: new chat ready"
    assert any("New Chat: the page did not answer within" in m for _, m in ctx.engine.lines)


@pytest.mark.unit
async def test_cancel_never_restarts_the_page(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _no_button)
    client = RestartClient()
    ok, reason = await nc.reset_to_new_chat(_ctx(client, cancel=lambda: True))
    assert not ok and "Page.navigate" not in client.sent


# ── transport: a timed-out/cancelled command removes ITS OWN pending entry ──


@pytest.mark.unit
async def test_timeout_pops_its_own_id_not_the_latest(monkeypatch):
    from app.browser.cdp import transport as tr

    async def no_wire(*_a):
        return None

    monkeypatch.setattr(tr, "_send_payload", no_wire)
    t = tr.CDPTransport.__new__(tr.CDPTransport)
    t._ws, t._connected, t._cmd_id, t._pending = object(), True, 0, {}
    slow = asyncio.ensure_future(t.send("Runtime.evaluate", {}, timeout=0.05))   # id 1
    await asyncio.sleep(0)
    other = asyncio.ensure_future(t.send("DOM.getDocument", {}, timeout=5))    # id 2
    with pytest.raises(TimeoutError):
        await slow
    assert list(t._pending) == [2], "the concurrent command must keep its entry"
    other.cancel()
    with pytest.raises(asyncio.CancelledError):
        await other
    assert t._pending == {}, "a cancelled command leaves no stale entry"

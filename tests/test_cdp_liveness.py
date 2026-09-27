"""A socket that went silent is re-dialled; a silent tab is told as such (I-72, 2026-09-27).

Owner log 18:05: after Submit both connections to the tab stopped answering —
even `Page.getNavigationHistory`, which Chrome answers in the browser process
while the page's scripts are stuck. The fake Chrome below (a real local
websocket server, RULE 8) can wedge ONE socket while new ones still answer.
"""
import asyncio
import json
import time

import pytest
import websockets

from app.browser import page_recovery as pr
from app.browser.cdp import liveness as lv
from app.browser.cdp.client import CDPClient
from app.browser.cdp.transport import _route

pytestmark = pytest.mark.unit


class FakeChrome:
    """Answers every command; `wedge()` silences the sockets open right now, `hang()` all."""

    def __init__(self):
        self.silent, self.hung, self.sockets, self.server = set(), False, [], None
        self.delay = 0.0                                  # a busy page: every reply comes late

    async def handler(self, ws):
        self.sockets.append(ws)
        await ws.send(json.dumps({"method": "Page.frameNavigated", "params": {}}))   # events come first
        async for raw in ws:
            if self.hung or ws in self.silent:
                continue
            await asyncio.sleep(self.delay)
            await ws.send(json.dumps({"id": json.loads(raw)["id"],
                                      "result": {"result": {"type": "number", "value": 1}}}))

    def wedge(self):
        self.silent.update(self.sockets)

    async def __aenter__(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/devtools/page/T1"
        return self

    async def __aexit__(self, *exc):
        self.server.close()


@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(pr, "PING_TIMEOUT_S", 0.3)
    monkeypatch.setattr(lv, "FRESH_PING_S", 0.5)
    monkeypatch.setattr(lv, "SECOND_PING_S", 0.3)
    monkeypatch.setattr(lv, "RECENT_RX_S", 0.0)       # I-73: nothing counts as "heard just now"


async def _client(chrome):
    client = CDPClient(host="127.0.0.1", port=int(chrome.url.split(":")[2].split("/")[0]))
    notes = []
    client.dialogs.report = notes.append
    assert await client.connect(chrome.url)
    return client, notes


def _timed_out(client):
    client.last_error, client.last_error_kind = "TimeoutError: CDP command Runtime.evaluate timed out after 30s", "transport"


async def test_a_fresh_socket_answers_a_live_tab_and_not_a_hung_one(quick):
    async with FakeChrome() as chrome:
        assert await lv.fresh_socket_answers(chrome.url) is True
        chrome.hung = True
        started = time.monotonic()
        assert await lv.fresh_socket_answers(chrome.url, timeout_s=0.3) is False
        assert time.monotonic() - started < 2


async def test_a_wedged_socket_is_redialled_and_the_same_client_answers_again(quick):
    async with FakeChrome() as chrome:
        client, notes = await _client(chrome)
        chrome.wedge()                                   # our socket is silent, the tab is not
        _timed_out(client)
        assert await pr.still_frozen(client) is False    # revived, so not frozen
        assert await client.evaluate("1") == 1 and client.last_error == ""
        assert notes[0].startswith("🔌 CDP socket went silent (last message ")
        assert notes[-1] == "🔌 CDP socket re-dialled — continuing"
        await client.disconnect()


async def test_a_silent_tab_stays_frozen_and_says_a_fresh_socket_was_silent_too(quick):
    async with FakeChrome() as chrome:
        client, notes = await _client(chrome)
        chrome.hung = True
        _timed_out(client)
        assert await pr.still_frozen(client) is True
        assert await pr.still_frozen(client) is True
        assert client.last_error.count("a fresh socket to the tab got no answer either") == 1
        assert "a fresh socket to the tab got no answer either" in pr.unresponsive_text(client)
        assert notes == []                               # nothing re-dialled, nothing claimed
        chrome.hung = False
        await client.disconnect()


def test_the_last_and_largest_messages_are_recorded_and_worded():
    class T:
        events = type("E", (), {"dispatch": staticmethod(lambda _d: None)})()
        _pending = {}
    t = T()
    _route(t, "x" * (3 * 1048576), {"method": "Network.webSocketFrameReceived"})
    _route(t, "y" * 2048, {"id": 7})
    assert t.last_rx["kind"] == "reply" and t.last_rx["bytes"] == 2048
    assert t.largest_rx == {"bytes": 3 * 1048576, "kind": "Network.webSocketFrameReceived"}
    assert lv.rx_text(t).endswith("reply 2.0 KB; largest 3.0 MB Network.webSocketFrameReceived")
    assert lv.rx_text(object()) == "nothing received yet"


async def test_a_client_without_a_url_is_not_redialled():
    class NoUrl:
        last_error, last_error_kind = "", ""
    assert await lv.revive_silent_socket(NoUrl()) is False


async def test_a_redial_whose_disconnect_hangs_still_connects(monkeypatch):
    monkeypatch.setattr(lv, "REDIAL_TIMEOUT_S", 0.1)

    class Stuck:
        async def disconnect(self):
            await asyncio.sleep(5)

        async def connect(self, _url):
            return True
    assert await lv._redial(Stuck(), "ws://x") is True


async def test_a_reporter_that_raises_does_not_break_the_revival():
    class Broken:
        def report(self, _m):
            raise RuntimeError("ui gone")
    client = type("C", (), {"dialogs": Broken()})()
    lv._tell(client, "note")                             # falls back to the python log


async def test_the_watchers_unanswered_tick_redials_a_wedged_socket_and_keeps_the_reason(quick):
    from app.browser.cdp_arena import state
    async with FakeChrome() as chrome:
        client, notes = await _client(chrome)
        chrome.wedge()
        _timed_out(client)
        hold = await state._unanswered(client)
        assert hold == {"unanswered": True, "error": "TimeoutError: CDP command Runtime.evaluate timed out after 30s"}
        assert notes[-1] == "🔌 CDP socket re-dialled — continuing"
        assert await client.evaluate("1") == 1           # the next Watcher tick reads the page again
        await client.disconnect()


# ── I-73: a busy page is not a wedged socket (owner log 2026-09-27 22:38) ──

async def test_a_socket_that_heard_chrome_just_now_is_not_redialled(quick, monkeypatch):
    monkeypatch.setattr(lv, "RECENT_RX_S", 30.0)
    async with FakeChrome() as chrome:
        client, notes = await _client(chrome)
        chrome.wedge()
        _timed_out(client)
        assert await pr.still_frozen(client) is True     # still waiting — but no re-dial
        assert await pr.still_frozen(client) is True
        assert len(chrome.sockets) == 1                  # not even a fresh socket was opened
        assert client.last_error.count("the socket is alive — the page itself is busy") == 1
        assert notes == []
        chrome.silent.clear()
        await client.disconnect()


async def test_a_page_that_just_came_back_answers_our_socket_without_a_redial(quick):
    async with FakeChrome() as chrome:
        client, notes = await _client(chrome)
        _timed_out(client)
        assert await lv.revive_silent_socket(client) is True
        assert len(chrome.sockets) == 2                  # ours + the throw-away one, no re-dial
        assert notes == [] and client.last_error == ""
        await client.disconnect()


async def test_a_late_reply_tells_how_long_the_page_was_busy_once_per_window(quick):
    async with FakeChrome() as chrome:
        client, notes = await _client(chrome)
        chrome.delay = 0.4
        assert await client.evaluate("1", timeout=0.1) is None
        assert await client.evaluate("1", timeout=0.1) is None
        await asyncio.sleep(1.0)
        late = [n for n in notes if n.startswith("⌛ Chrome answered Runtime.evaluate ")]
        assert len(late) == 1 and late[0].endswith("the app's checks take well under a second)")
        assert 0.3 < client.last_late_s < 1.5 and client.timed_out == {}
        chrome.delay = 0.0
        await client.disconnect()


def test_the_timed_out_book_is_bounded():
    t = type("T", (), {})()
    for i in range(lv.LATE_BOOK_MAX + 8):
        lv.note_timed_out(t, i, "Runtime.evaluate", 5.0)
    assert len(t.timed_out) == lv.LATE_BOOK_MAX and 0 not in t.timed_out
    lv.note_late_reply(t, None)                          # an event has no id: nothing happens

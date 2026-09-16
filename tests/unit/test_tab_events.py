"""Unit tests — TabEventWatcher: browser endpoint discovery, event filtering, stop."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.browser.tab_events import (
    TARGET_EVENTS,
    TabEventWatcher,
    _browser_ws_url,
    split_endpoint,
)


@pytest.mark.unit
@pytest.mark.parametrize("payload,expected", [
    ({"webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/abc"}, "ws://127.0.0.1:9223/devtools/browser/abc"),
    ({"web_socket_debugger_url": "ws://x/devtools/browser/1"}, "ws://x/devtools/browser/1"),
    ({"Browser": "Chrome/126"}, ""),
    (None, ""),
    ("nope", ""),
])
def test_browser_ws_url_extraction(payload, expected):
    assert _browser_ws_url(payload) == expected


@pytest.mark.unit
@pytest.mark.parametrize("endpoint,expected", [
    ("127.0.0.1:9223", ("127.0.0.1", 9223)),
    ("localhost:9222", ("localhost", 9222)),
    ("", ("127.0.0.1", 9222)),
    ("nonsense", ("nonsense", 9222)),
])
def test_split_endpoint(endpoint, expected):
    assert split_endpoint(endpoint) == expected


@pytest.mark.unit
@pytest.mark.parametrize("message,expected", [
    (json.dumps({"method": "Target.targetCreated", "params": {}}), "Target.targetCreated"),
    (json.dumps({"method": "Target.targetDestroyed"}), "Target.targetDestroyed"),
    (json.dumps({"method": "Target.targetInfoChanged"}), "Target.targetInfoChanged"),
    (json.dumps({"method": "Runtime.consoleAPICalled"}), ""),
    (json.dumps({"id": 1, "result": {}}), ""),
    ("not json", ""),
])
def test_event_method_only_accepts_target_events(message, expected):
    assert TabEventWatcher._event_method(message) == expected


@pytest.mark.unit
def test_target_events_cover_new_and_closed_tabs():
    assert "Target.targetCreated" in TARGET_EVENTS
    assert "Target.targetDestroyed" in TARGET_EVENTS


@pytest.mark.unit
def test_watcher_fires_callback_and_stops_cleanly():
    events: list = []
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=events.append, retry_sec=0.05)
    # Drive the event path directly — no Chrome in unit tests
    watcher._on_event("Target.targetCreated")
    assert events == ["Target.targetCreated"]
    assert watcher.endpoint == "127.0.0.1:9223"
    watcher.stop()  # idempotent, no thread started
    assert watcher.active is False


@pytest.mark.unit
def test_session_backs_off_when_no_browser_endpoint(monkeypatch):
    """No /json/version answer → the watcher retries instead of crashing."""
    seen: list = []
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=lambda kind: seen.append(kind), retry_sec=0.05)

    async def no_endpoint():
        return ""

    monkeypatch.setattr(watcher, "_discover_endpoint", no_endpoint)
    assert watcher.start() is True
    thread = watcher._thread
    thread.join(timeout=0.3)
    assert thread.is_alive(), "watcher keeps retrying while Chrome is down"
    assert seen == []
    watcher.stop(timeout=2.0)
    assert thread.is_alive() is False
    assert watcher.active is False


@pytest.mark.unit
def test_start_is_false_without_websockets(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "websockets", None)
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=lambda kind: None)
    assert watcher.start() is False
    assert watcher._thread is None
    watcher.stop()  # safe no-op


class FakeSocket:
    """Async-iterable websocket stub that records what was sent."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.sent: list = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        async def gen():
            for m in self._messages:
                yield m
        return gen()


class FakeWebsockets:
    def __init__(self, socket):
        self._socket = socket
        self.urls: list = []

    def connect(self, url, **kwargs):
        self.urls.append((url, kwargs))
        socket = self._socket

        class _Ctx:
            async def __aenter__(self_inner):
                return socket

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_listen_subscribes_to_targets_and_forwards_tab_events():
    events: list = []
    logs: list = []
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=events.append,
                              logger=lambda m, lvl="info": logs.append((m, lvl)))
    socket = FakeSocket([
        json.dumps({"id": 1, "result": {}}),
        json.dumps({"method": "Target.targetCreated", "params": {"targetInfo": {"url": "https://arena.ai/"}}}),
        json.dumps({"method": "Runtime.consoleAPICalled"}),
        json.dumps({"method": "Target.targetDestroyed"}),
    ])
    fake = FakeWebsockets(socket)
    await watcher._listen(fake, "ws://127.0.0.1:9223/devtools/browser/xyz")
    assert fake.urls[0][0] == "ws://127.0.0.1:9223/devtools/browser/xyz"
    assert fake.urls[0][1]["ping_interval"] is None  # never let pings drop the stream
    assert socket.sent[0]["method"] == "Target.setDiscoverTargets"
    assert events == ["Target.targetCreated", "Target.targetDestroyed"]
    assert watcher.active is True
    assert any("Listening for new-tab events" in m for m, _l in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_events_stops_when_watcher_is_stopped():
    events: list = []
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=events.append)
    watcher._stop.set()
    await watcher._read_events(FakeSocket([json.dumps({"method": "Target.targetCreated"})]))
    assert events == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_callback_error_does_not_break_the_stream():
    def boom(_kind):
        raise RuntimeError("callback exploded")

    watcher = TabEventWatcher("127.0.0.1:9223", on_event=boom)
    await watcher._read_events(FakeSocket([
        json.dumps({"method": "Target.targetCreated"}),
        json.dumps({"method": "Target.targetDestroyed"}),
    ]))  # both messages consumed, no exception escapes


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_endpoint_reads_browser_ws_url(monkeypatch):
    from app.browser import cdp_client

    asked: list = []

    def fake_fetch(url, timeout=2.0):
        asked.append((url, timeout))
        return {"webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/abc"}, ""

    monkeypatch.setattr(cdp_client, "_fetch_json_sync", fake_fetch)
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=lambda kind: None)
    assert await watcher._discover_endpoint() == "ws://127.0.0.1:9223/devtools/browser/abc"
    assert asked[0][0] == "http://127.0.0.1:9223/json/version"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discover_endpoint_returns_empty_on_error(monkeypatch):
    from app.browser import cdp_client

    monkeypatch.setattr(cdp_client, "_fetch_json_sync", lambda url, timeout=2.0: (None, "URLError"))
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=lambda kind: None)
    assert await watcher._discover_endpoint() == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_reconnects_after_the_stream_drops(monkeypatch):
    """A dropped browser websocket must not end the watch (spec 03: keep confirming)."""
    events: list = []
    watcher = TabEventWatcher("127.0.0.1:9223", on_event=events.append, retry_sec=0.05)

    attempts: list = []

    async def endpoint():
        attempts.append(1)
        return "ws://127.0.0.1:9223/devtools/browser/abc"

    class Dropping(FakeWebsockets):
        def connect(self, url, **kwargs):
            socket = FakeSocket([json.dumps({"method": "Target.targetCreated"})])

            class _Ctx:
                async def __aenter__(self_inner):
                    return socket

                async def __aexit__(self_inner, *exc):
                    raise ConnectionError("socket gone")

            return _Ctx()

    monkeypatch.setattr(watcher, "_discover_endpoint", endpoint)
    monkeypatch.setitem(__import__("sys").modules, "websockets", Dropping(None))
    watcher.start()
    await asyncio.sleep(0.3)
    watcher.stop(timeout=2.0)
    assert len(attempts) >= 2  # retried after the drop

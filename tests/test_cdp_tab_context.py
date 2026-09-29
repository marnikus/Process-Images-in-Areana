"""Browser-target CDP operations must preserve the source target's context."""
from __future__ import annotations

import asyncio

from app.browser.cdp.tabs import open_tab_in_same_context, target_context


class BrowserClient:
    def __init__(self, targets):
        self.targets = targets
        self.calls = []
        self._current_ws_url = "ws://h:9333/devtools/browser/F"

    async def send(self, method, params=None, timeout=30):
        self.calls.append((method, params or {}))
        if method == "Target.getTargets":
            return {"result": {"targetInfos": self.targets}}
        if method == "Target.createTarget":
            return {"result": {"targetId": "NEW"}}
        raise AssertionError(method)


def test_target_context_distinguishes_default_context_from_missing_target():
    client = BrowserClient([{"targetId": "OLD", "type": "page"}])
    assert asyncio.run(target_context(client, "OLD")) == (True, None)
    assert asyncio.run(target_context(client, "MISSING")) == (False, None)


def test_target_context_reads_non_default_browser_context():
    client = BrowserClient([{"targetId": "OLD", "browserContextId": "CTX-7"}])
    assert asyncio.run(target_context(client, "OLD")) == (True, "CTX-7")


def test_create_target_uses_browser_level_protocol_and_exact_context(monkeypatch):
    client = BrowserClient([{"targetId": "OLD", "browserContextId": "CTX-7"}])

    async def tabs(host, port, timeout=3.0):
        from app.browser.cdp.tabs import TabInfo
        return [TabInfo("NEW", "", "https://arena.ai/image/direct", "ws://h:9333/devtools/page/NEW")], "", []

    monkeypatch.setattr("app.browser.cdp.tabs.fetch_tabs_sync", lambda *a, **k: (
        [__import__("app.browser.cdp.tabs", fromlist=["TabInfo"]).TabInfo(
            "NEW", "", "https://arena.ai/image/direct", "ws://h:9333/devtools/page/NEW")], "", []))
    tab, err = asyncio.run(open_tab_in_same_context(client, ("h", 9333),
                                                    "https://arena.ai/image/direct", "OLD"))
    assert err == "" and tab.id == "NEW"
    assert client.calls == [
        ("Target.getTargets", {}),
        ("Target.createTarget", {"url": "https://arena.ai/image/direct", "browserContextId": "CTX-7"}),
    ]


def test_create_target_omits_context_only_for_verified_default_context(monkeypatch):
    client = BrowserClient([{"targetId": "OLD", "type": "page"}])
    monkeypatch.setattr("app.browser.cdp.tabs.fetch_tabs_sync", lambda *a, **k: (
        [__import__("app.browser.cdp.tabs", fromlist=["TabInfo"]).TabInfo(
            "NEW", "", "https://arena.ai/image/direct", "ws://h:9333/devtools/page/NEW")], "", []))
    tab, err = asyncio.run(open_tab_in_same_context(client, ("h", 9333),
                                                    "https://arena.ai/image/direct", "OLD"))
    assert err == "" and tab.id == "NEW"
    assert client.calls[-1] == ("Target.createTarget", {"url": "https://arena.ai/image/direct"})


def test_create_target_refuses_page_websocket_instead_of_browser_websocket():
    client = BrowserClient([{"targetId": "OLD"}])
    client._current_ws_url = "ws://h:9333/devtools/page/OLD"
    tab, err = asyncio.run(open_tab_in_same_context(client, ("h", 9333),
                                                    "https://arena.ai/image/direct", "OLD"))
    assert tab is None and "browser-level" in err
    assert all(method != "Target.createTarget" for method, _ in client.calls)


def test_create_target_refuses_when_old_target_context_cannot_be_proven():
    client = BrowserClient([])
    tab, err = asyncio.run(open_tab_in_same_context(client, ("h", 9333),
                                                    "https://arena.ai/image/direct", "OLD"))
    assert tab is None and "context" in err.lower()
    assert all(method != "Target.createTarget" for method, _ in client.calls)

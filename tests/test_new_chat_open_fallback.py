"""New-chat reset falls back to opening the New Chat page itself (I-69, 2026-09-27).

Owner report: "after failed page the restart of page and return to new chat
was never happened" — the log stopped at `🔍 FIND phase: searching New Chat`.
The reset had exactly one way back (click the sidebar link); when that click
failed, or the page never reached a clean new chat, the tab stayed in the old
chat. Now a failed click or load opens the same link's path (`/image/direct`,
site_adapter — RULE 21) on the tab's own origin with CDP `Page.navigate`
(a full page restart) and waits for the same readiness proof.
"""

import pytest

from app.browser import new_chat as nc
from app.browser.probe_selectors import new_chat_path
from tests.test_new_chat import FakeCtrl, FakeEngine, make_ctx

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

CHAT_URL = "https://arena.ai/c/01a0e200-ed96-708b-adf6-102f5b34f937"


class NavClient:
    """CDP boundary: a composer that is only clean after a real navigation."""

    def __init__(self, url=CHAT_URL, nav_error=None, clean_before_nav=False):
        self.url, self.nav_error, self.clean = url, nav_error, clean_before_nav
        self.sent = []

    async def evaluate(self, expr, await_promise=True):
        if "readyState" in expr:
            return {"complete": True, "readyState": "complete", "hasTextarea": True}
        return {"empty": self.clean, "len": 0 if self.clean else 42}

    async def send(self, method, params=None, timeout=30):
        self.sent.append((method, params or {}))
        if method == "Page.getNavigationHistory":
            return {"currentIndex": 0, "entries": [{"url": self.url}]}
        if self.nav_error:
            raise TimeoutError(self.nav_error)
        self.clean = True
        return {"frameId": "F1"}


def _click(result):
    async def fake(client, req, engine=None):
        return result
    return fake


def _navigations(client):
    return [p.get("url") for m, p in client.sent if m == "Page.navigate"]


async def test_a_failed_click_opens_the_new_chat_page_on_the_tabs_own_origin(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _click("not-found"))
    client, engine = NavClient(), FakeEngine()
    ok, reason = await nc.reset_to_new_chat(make_ctx(client=client, engine=engine))
    assert ok is True, reason
    assert _navigations(client) == ["https://arena.ai" + new_chat_path()]
    assert any("opening" in m and new_chat_path() in m for m, _ in engine.records)
    assert engine.records[-1][1] == "success"


async def test_a_click_whose_page_never_gets_clean_is_restarted(monkeypatch):
    """Clicked, but the composer still holds text at the deadline → open the page directly."""
    monkeypatch.setattr(nc, "find_and_click", _click("ok"))
    client = NavClient()
    ok, reason = await nc.reset_to_new_chat(make_ctx(client=client, timeout=1))
    assert ok is True, reason
    assert len(_navigations(client)) == 1


async def test_a_clean_click_never_navigates(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _click("ok"))
    client = NavClient(clean_before_nav=True)
    ok, _ = await nc.reset_to_new_chat(make_ctx(client=client))
    assert ok is True and _navigations(client) == []


async def test_both_ways_failing_is_reported_with_both_causes(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _click("not-found"))
    client, engine = NavClient(nav_error="CDP command Page.navigate timed out after 15s"), FakeEngine()
    ok, reason = await nc.reset_to_new_chat(make_ctx(client=client, engine=engine))
    assert ok is False
    assert "not found" in reason and "timed out" in reason
    assert engine.records[-1][1] == "error"


async def test_a_tab_with_no_known_page_url_is_not_guessed(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _click("not-found"))
    client = NavClient(url="about:blank")
    ok, reason = await nc.reset_to_new_chat(make_ctx(client=client))
    assert ok is False and _navigations(client) == []
    assert "page address" in reason


async def test_a_cancelled_reset_does_not_navigate(monkeypatch):
    monkeypatch.setattr(nc, "find_and_click", _click("not-found"))
    client = NavClient()
    ok, reason = await nc.reset_to_new_chat(make_ctx(client=client, cancel=lambda: True))
    assert ok is False and _navigations(client) == []
    assert "not found" in reason   # the honest cause; a cancelled run never opens pages


def test_the_path_is_the_new_chat_links_own_href():
    from app.browser.probe_selectors import new_chat_primary
    assert new_chat_primary() == f'a[href="{new_chat_path()}"]'
    assert FakeCtrl  # shared fakes stay importable

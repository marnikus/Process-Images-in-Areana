"""Every way a fresh tab can fail to be provable — the opener strategies themselves (R3).

`open_in_profile` may only ever hand back a tab the *browser* placed in the job tab's context;
anything else is a reason. The precedence matters for the owner bug: a tab that landed in another
profile outranks a plain failure in the refusal text. Design:
docs/archive/2026-09-29-new-chat-new-tab-profile-truth/design.md §3 R3.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import new_tab_open as o

pytestmark = pytest.mark.unit

CTX = "CTX-2"
SPEC = o.OpenSpec(url="https://arena.ai/image/direct", context_id=CTX, timeout_sec=1.0)


class FakeBrowser:
    """The `BrowserTargets` surface with a scripted outcome per call."""

    def __init__(self):
        self.tabs: dict[str, str] = {}      # id → context the browser really put it in
        self.targets_err = ""
        self.create_result: tuple = ("NEW", "")
        self.create_ctx = CTX
        self.closed: list = []
        self.list_created = True

    def _infos(self) -> list:
        return [{"targetId": tid, "type": "page", "url": "https://arena.ai/x",
                 **({"browserContextId": ctx} if ctx else {})} for tid, ctx in self.tabs.items()]

    async def targets(self):
        return ([], self.targets_err) if self.targets_err else (self._infos(), "")

    async def create(self, url, context_id):
        tab_id, err = self.create_result
        if tab_id and self.list_created:
            self.tabs[tab_id] = self.create_ctx
        return tab_id, err

    async def close(self, tab_id):
        self.tabs.pop(tab_id, None)
        self.closed.append(tab_id)
        return True, ""


def _popup(monkeypatch, browser, tab_id="POP", ctx=CTX, ok=True, why=""):
    """Replace the real page opener with a scripted one that may add a tab to the browser."""
    async def fake(client, url, timeout):
        if tab_id:
            browser.tabs[tab_id] = ctx
        return ok, why
    monkeypatch.setattr(o, "open_tab_via_page", fake)


def test_a_tab_chrome_created_in_the_job_context_is_proven():
    b = FakeBrowser()
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert (opened.tab_id, opened.reason, opened.wrong_profile) == ("NEW", "", False)
    assert b.closed == []


def test_a_create_that_lands_in_another_context_is_closed_and_reported_as_profile():
    b = FakeBrowser()
    b.create_ctx = "OTHER-CTX"
    opened = asyncio.run(o.open_in_profile(b, None, SPEC))
    assert opened.wrong_profile and "another profile" in opened.reason
    assert b.tabs == {} and b.closed == ["NEW"]          # the foreign tab never stays behind


def test_a_create_that_is_refused_falls_through_to_the_pages_own_tab(monkeypatch):
    b = FakeBrowser()
    b.create_result = ("", "Failed to find browser context with id CTX-2")
    _popup(monkeypatch, b)
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert opened.tab_id == "POP" and not opened.wrong_profile


def test_a_blocked_popup_reports_the_pages_own_words(monkeypatch):
    b = FakeBrowser()
    b.create_result = ("", "Failed to find browser context with id CTX-2")
    _popup(monkeypatch, b, tab_id="", ok=False, why="window.open returned null (popup blocked)")
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert opened.tab_id == "" and "popup blocked" in opened.reason


def test_a_popup_that_opens_nothing_is_a_timeout_not_a_pass(monkeypatch):
    b = FakeBrowser()
    b.create_result = ("", "refused")
    monkeypatch.setattr(o, "_POLL_SEC", 0.01)
    _popup(monkeypatch, b, tab_id="", ok=True)
    opened = asyncio.run(o.open_in_profile(b, object(), o.OpenSpec(SPEC.url, CTX, 0.05)))
    assert opened.tab_id == "" and "no tab" in opened.reason


def test_a_popup_tab_in_the_wrong_context_is_closed_and_reported_as_profile(monkeypatch):
    b = FakeBrowser()
    b.create_result = ("", "refused")
    _popup(monkeypatch, b, ctx="OTHER-CTX")
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert opened.wrong_profile and "another profile" in opened.reason and b.closed == ["POP"]


def test_a_created_tab_the_browser_does_not_list_is_closed_as_unprovable():
    b = FakeBrowser()
    b.create_result = ("GHOST", "")          # the create answered, the list never shows it
    b.list_created = False
    opened = asyncio.run(o.open_in_profile(b, None, SPEC))
    assert opened.tab_id == "" and "not listed" in opened.reason
    assert not opened.wrong_profile and b.closed == ["GHOST"]


def test_a_browser_that_stops_answering_is_a_reason_not_a_wrong_profile():
    b = FakeBrowser()
    b.targets_err = "Target.getTargets: socket gone"
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert opened.tab_id == "" and "socket gone" in opened.reason and not opened.wrong_profile
    assert b.closed == ["NEW"]


def test_no_client_on_the_job_tab_means_no_page_opener():
    b = FakeBrowser()
    b.create_result = ("", "refused")
    opened = asyncio.run(o.open_in_profile(b, None, SPEC))
    assert opened.tab_id == "" and "job tab" in opened.reason


def test_the_refusal_names_the_wrong_profile_first(monkeypatch):
    """The A2 wording: a tab seen in another profile is the first reason of record."""
    b = FakeBrowser()
    b.create_ctx = "OTHER-CTX"
    _popup(monkeypatch, b, tab_id="", ok=False, why="window.open returned null (popup blocked)")
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert opened.reason.startswith("the new tab landed in another profile")
    assert opened.wrong_profile is True


def test_a_list_that_dies_while_waiting_for_the_popup_is_a_reason(monkeypatch):
    """The browser answered before the popup and stops answering while we wait for its tab."""
    b = FakeBrowser()
    b.create_result = ("", "refused")
    calls = {"n": 0}
    real = b.targets

    async def flaky():
        calls["n"] += 1
        return await real() if calls["n"] == 1 else ([], "Target.getTargets: socket gone")
    monkeypatch.setattr(b, "targets", flaky)
    monkeypatch.setattr(o, "_POLL_SEC", 0.01)
    _popup(monkeypatch, b, tab_id="", ok=True)
    opened = asyncio.run(o.open_in_profile(b, object(), SPEC))
    assert opened.tab_id == "" and "socket gone" in opened.reason and not opened.wrong_profile

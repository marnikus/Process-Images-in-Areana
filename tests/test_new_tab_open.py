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
        self.openers: dict[str, str] = {}   # id → the tab whose page opened it (TargetInfo.openerId)
        self.targets_err = ""
        self.create_result: tuple = ("NEW", "")
        self.create_ctx = CTX
        self.ctx_answer: tuple = ({CTX}, "")   # `Target.getBrowserContexts` — (creatable ids, err)
        self.closed: list = []
        self.list_created = True

    def _infos(self) -> list:
        return [{"targetId": tid, "type": "page", "url": "https://arena.ai/x",
                 **({"browserContextId": ctx} if ctx else {}),
                 **({"openerId": self.openers[tid]} if tid in self.openers else {})}
                for tid, ctx in self.tabs.items()]

    async def targets(self):
        return ([], self.targets_err) if self.targets_err else (self._infos(), "")

    async def get_browser_contexts(self):
        return self.ctx_answer

    async def create(self, url, context_id):
        tab_id, err = self.create_result
        if tab_id and self.list_created:
            self.tabs[tab_id] = self.create_ctx
        return tab_id, err

    async def close(self, tab_id):
        self.tabs.pop(tab_id, None)
        self.openers.pop(tab_id, None)
        self.closed.append(tab_id)
        return True, ""


def _popup(monkeypatch, browser, tab_id="POP", ctx=CTX, ok=True, why="", opener=""):
    """Replace the real page opener with a scripted one that may add a tab to the browser."""
    async def fake(client, url, timeout):
        if tab_id:
            browser.tabs[tab_id] = ctx
            if opener:
                browser.openers[tab_id] = opener
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


# ── v6: the fresh tab must be OURS by opener identity, and create must know its place ───
# Owner report 2026-09-30 ("bug appear again"): design docs/archive/2026-09-30-new-tab-opener-proof/design.md

def _ours_spec(opener="OLD"):
    return o.OpenSpec(SPEC.url, CTX, 1.0, opener_id=opener)


def test_the_popup_tab_is_identified_by_its_opener_never_by_sort_order(monkeypatch):
    """Two fresh tabs appear (another worker's sorts first): adopt only the one OUR page opened."""
    b = FakeBrowser()
    b.create_result = ("", "refused")

    async def two_tabs(client, url, timeout):
        b.tabs["A-STRAY"], b.openers["A-STRAY"] = CTX, "OTHER-TAB"   # sorts first, not ours
        b.tabs["POP"], b.openers["POP"] = CTX, "OLD"                 # our page's own tab
        return True, ""
    monkeypatch.setattr(o, "open_tab_via_page", two_tabs)
    opened = asyncio.run(o.open_in_profile(b, object(), _ours_spec()))
    assert opened.tab_id == "POP"
    assert "A-STRAY" in b.tabs and b.closed == []     # the stranger stays for its own handover


def test_a_stranger_fresh_tab_is_never_adopted_and_never_closed(monkeypatch):
    """Only a foreign-opener tab appears: refusal — and it is left for whoever opened it."""
    b = FakeBrowser()
    b.create_result = ("", "refused")
    _popup(monkeypatch, b, tab_id="A-STRAY", ctx=CTX, opener="OTHER-TAB")
    monkeypatch.setattr(o, "_POLL_SEC", 0.01)
    opened = asyncio.run(o.open_in_profile(b, object(), o.OpenSpec(SPEC.url, CTX, 0.1, opener_id="OLD")))
    assert opened.tab_id == "" and not opened.wrong_profile
    assert "A-STRAY" in b.tabs and b.closed == []
    assert "opener" in opened.reason.lower()


def test_create_is_skipped_when_the_browser_says_the_context_is_not_creatable(monkeypatch):
    """A regular profile: firing create only flashes a tab into the default profile — never fire it."""
    b = FakeBrowser()
    b.ctx_answer = (set(), "")            # Chrome can create into no listed context
    b.create_ctx = "OTHER-CTX"            # the default-landing shape would show right here
    b.create_result = ("NEW", "")
    calls: list = []

    async def record_create(url, ctx):
        calls.append((url, ctx))
        return "NEW", ""
    b.create = record_create
    _popup(monkeypatch, b, opener="OLD")
    opened = asyncio.run(o.open_in_profile(b, object(), _ours_spec()))
    assert opened.tab_id == "POP"
    assert calls == [] and b.closed == []          # no create fired, nothing to roll back


def test_a_creatable_context_still_uses_the_create_target(monkeypatch):
    """A context Chrome honours (DevTools-created) keeps the cheaper opener — no page involved."""
    b = FakeBrowser()                              # ctx_answer lists CTX as creatable

    async def no_popup(client, url, timeout):
        raise AssertionError("the page opener must not run when create works")
    monkeypatch.setattr(o, "open_tab_via_page", no_popup)
    opened = asyncio.run(o.open_in_profile(b, object(), _ours_spec()))
    assert opened.tab_id == "NEW" and b.closed == []


def test_the_default_context_still_creates_without_an_id(monkeypatch):
    """The default profile needs no context id, so an empty creatable list does not block it."""
    b = FakeBrowser()
    b.ctx_answer = (set(), "")
    b.create_ctx = ""                              # the tab lands in the default context
    opened = asyncio.run(o.open_in_profile(b, object(), o.OpenSpec(SPEC.url, "", 1.0)))
    assert opened.tab_id == "NEW" and not opened.wrong_profile


def test_an_unanswerable_context_list_keeps_the_create_attempt():
    """When the browser cannot answer the creatable set, today's create-first order stands."""
    b = FakeBrowser()
    b.ctx_answer = (set(), "socket gone")
    opened = asyncio.run(o.open_in_profile(b, object(), _ours_spec()))
    assert opened.tab_id == "NEW" and not opened.wrong_profile


def test_the_refusal_names_the_page_route_when_create_was_skipped(monkeypatch):
    """RULE 2: the log must say the job tab's own page was the only route — and why it failed."""
    b = FakeBrowser()
    b.ctx_answer = (set(), "")
    _popup(monkeypatch, b, tab_id="", ok=False, why="window.open returned null (popup blocked)")
    opened = asyncio.run(o.open_in_profile(b, object(), _ours_spec()))
    assert opened.tab_id == "" and opened.wrong_profile is False
    assert "page" in opened.reason and "popup blocked" in opened.reason


# ── v7 merge (branch 1's R7b): the job tab's own socket is the honest popup fallback ──────
# Merge of arena/01a0f1cf's R7b onto the v6 opener rules — design:
# docs/archive/2026-09-30-opener-fallback-merge/design.md

def test_a_popup_that_names_another_opener_marks_the_wrong_opener(monkeypatch):
    """R7b's trigger: a fresh tab claimed by ANOTHER page is the drifted-socket evidence."""
    b = FakeBrowser()
    b.create_result = ("", "refused")
    _popup(monkeypatch, b, tab_id="A-STRAY", ctx=CTX, opener="OTHER-TAB")
    monkeypatch.setattr(o, "_POLL_SEC", 0.01)
    opened = asyncio.run(o.open_in_profile(b, object(), o.OpenSpec(SPEC.url, CTX, 0.1, opener_id="OLD")))
    assert opened.tab_id == "" and opened.wrong_opener is True
    assert "A-STRAY" in b.tabs and b.closed == []


def test_a_blocked_popup_is_not_wrong_opener_evidence(monkeypatch):
    """A blocked popup opened nothing — there is no stranger to prove the socket lied."""
    b = FakeBrowser()
    b.create_result = ("", "refused")
    _popup(monkeypatch, b, tab_id="", ok=False, why="window.open returned null (popup blocked)")
    opened = asyncio.run(o.open_in_profile(b, object(), _ours_spec()))
    assert opened.tab_id == "" and opened.wrong_opener is False


def test_dialing_a_socket_that_answers_nothing_is_no_client(monkeypatch):
    """R7b's seam is real: an unreadable or refusing socket yields no client, never a raise."""
    assert asyncio.run(o._dial_page("")) is None

    class SilentClient:
        def __init__(self, *args):
            pass

        async def connect(self, ws_url):
            return False                      # the page socket refuses the connection

    monkeypatch.setattr(o, "CDPClient", SilentClient)
    assert asyncio.run(o._dial_page("ws://127.0.0.1:9/devtools/page/OLD")) is None


def test_a_socket_client_that_raises_is_no_client(monkeypatch):
    """R7b: a connect that explodes yields no client — the refusal, never an exception."""

    class RaisingClient:
        def __init__(self, *args):
            pass

        async def connect(self, ws_url):
            raise RuntimeError("websocket exploded")

    monkeypatch.setattr(o, "CDPClient", RaisingClient)
    assert asyncio.run(o._dial_page("ws://127.0.0.1:9/devtools/page/OLD")) is None

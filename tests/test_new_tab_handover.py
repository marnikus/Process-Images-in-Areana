"""I-79 — "Start new chat as new tab": the worker moves to a fresh tab, the old tab closes.

Real PagePool, real AliasBook, real UrlRows; the browser (tab list, open, close) and
the CDP clients are fakes. Design: docs/archive/2026-09-28-new-chat-new-tab/design.md.
"""
from __future__ import annotations

import asyncio
import io
import urllib.error
from types import SimpleNamespace

import pytest

from app.browser.cdp import tabs as cdp_tabs
from app.browser.cdp.tabs import TabInfo
from app.browser.page_pool import PagePool, retarget_page
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.core.tab_alias import AliasBook
from app.services import new_tab
from app.services.cooldown_service import FinishCtx

NEW_URL = "https://arena.ai/image/direct?model_a=max"


# ── browser pieces ──────────────────────────────────────────────────────────

def test_alias_book_adopt_moves_the_number_and_owner_to_the_new_tab():
    book = AliasBook()
    no = book.no_for("OLD")
    book.remember("OLD", "user@example.com")
    book.adopt("NEW", "OLD")
    assert book.no_for("NEW") == no and book.owner_for("NEW") == "user@example.com"
    assert "OLD" not in book.as_dict()


def test_alias_book_adopt_of_an_unknown_tab_changes_nothing():
    book = AliasBook()
    book.adopt("NEW", "NOPE")
    assert len(book) == 0


def _pool_with(*tab_ids):
    pool = PagePool(alias_book=AliasBook())
    for tid in tab_ids:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://h:9/devtools/page/{tid}", url="https://arena.ai/c/1"))
    return pool


def test_retarget_page_keeps_the_worker_under_the_new_key_in_pool_order():
    pool = _pool_with("A", "OLD", "B")
    page = pool.get_page("OLD")
    page.cooldown_until, page.jobs_completed, page.captcha_count = 99.0, 7, 2
    number, worker = page.alias_no, page.worker_no
    client, ctrl = object(), object()
    pool.register_client("OLD", client, ctrl)
    assert retarget_page(pool, "OLD", TabInfo("NEW", "t", NEW_URL, "ws://h:9/devtools/page/NEW"))
    moved = pool.get_page("NEW")
    assert pool.get_page("OLD") is None and moved is page
    assert (moved.tab_id, moved.ws_url, moved.url) == ("NEW", "ws://h:9/devtools/page/NEW", NEW_URL)
    assert (moved.cooldown_until, moved.jobs_completed, moved.captcha_count) == (99.0, 7, 2)
    assert (moved.alias_no, moved.worker_no) == (number, worker)
    assert pool.get_clients("NEW") == (client, ctrl) and pool.get_clients("OLD") == (None, None)
    assert [p["tab_id"] for p in pool.status_snapshot()["pages"]] == ["A", "NEW", "B"]


def test_retarget_page_of_a_tab_not_in_the_pool_is_false():
    assert retarget_page(_pool_with("A"), "OLD", TabInfo("NEW", "", NEW_URL, "ws://x")) is False


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_open_tab_sync_puts_the_percent_encoded_url(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=0):
        seen["method"], seen["url"] = req.get_method(), req.full_url
        return _Resp(b'{"id":"N1","title":"","url":"%s","type":"page",'
                     b'"webSocketDebuggerUrl":"ws://127.0.0.1:9/devtools/page/N1"}' % NEW_URL.encode())
    monkeypatch.setattr(cdp_tabs.urllib.request, "urlopen", fake_urlopen)
    tab, err = cdp_tabs.open_tab_sync("127.0.0.1", 9, NEW_URL)
    assert err == "" and tab.id == "N1" and tab.url == NEW_URL
    assert seen["method"] == "PUT"
    assert seen["url"] == "http://127.0.0.1:9/json/new?https%3A%2F%2Farena.ai%2Fimage%2Fdirect%3Fmodel_a%3Dmax"


def test_open_tab_sync_failure_is_a_reason_not_a_raise(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(cdp_tabs.urllib.request, "urlopen", boom)
    tab, err = cdp_tabs.open_tab_sync("127.0.0.1", 9, NEW_URL)
    assert tab is None and "refused" in err


@pytest.mark.parametrize("raised, ok", [(None, True), (404, True), (500, False)])
def test_close_tab_sync_404_means_already_closed(monkeypatch, raised, ok):
    def fake_urlopen(req, timeout=0):
        if raised:
            raise urllib.error.HTTPError(req.full_url, raised, "x", {}, None)
        return _Resp(b"Target is closing")
    monkeypatch.setattr(cdp_tabs.urllib.request, "urlopen", fake_urlopen)
    assert cdp_tabs.close_tab_sync("127.0.0.1", 9, "OLD")[0] is ok


# ── the handover ────────────────────────────────────────────────────────────

class FakeBrowser:
    """The endpoint's tab list; `close_ignored` = the browser refuses to close."""

    def __init__(self, *ids):
        self.ids = list(ids)
        self.opened, self.closed = [], []
        self.close_ignored = False
        self.open_error = ""

    def open(self, host, port, url):
        if self.open_error:
            return None, self.open_error
        tid = f"NEW{len(self.opened) + 1}"
        self.opened.append(url)
        self.ids.append(tid)
        return TabInfo(tid, "", url, f"ws://{host}:{port}/devtools/page/{tid}"), ""

    def close(self, host, port, tab_id):
        self.closed.append(tab_id)
        if not self.close_ignored and tab_id in self.ids:
            self.ids.remove(tab_id)
        return True, ""

    def listing(self, host, port, timeout=3.0):
        return [TabInfo(i, "", "", f"ws://x/{i}") for i in self.ids], "", []


class FakeClient:
    def __init__(self, tab_id):
        self._host, self._port = "127.0.0.1", 9333
        self._current_tab_id = tab_id
        self.moves = []

    async def connect(self, ws_url):
        self.moves.append(ws_url)
        self._current_tab_id = ws_url.rsplit("/", 1)[-1]
        return True


def _world(monkeypatch, *, ready=(True, "new chat ready"), is_new=(True, "new chat")):
    browser = FakeBrowser("OLD", "OTHER")
    monkeypatch.setattr(new_tab, "open_tab_sync", browser.open)
    monkeypatch.setattr(new_tab, "close_tab_sync", browser.close)
    monkeypatch.setattr(new_tab, "fetch_tabs_sync", browser.listing)
    monkeypatch.setattr(new_tab, "_GONE_POLL_SEC", 0.01)
    monkeypatch.setattr(new_tab, "_GONE_WAIT_SEC", 0.05)

    async def fake_ready(reset_ctx):
        return ready
    async def fake_read(client):
        return is_new
    monkeypatch.setattr(new_tab, "wait_new_chat_ready", fake_ready)
    monkeypatch.setattr(new_tab, "read_chat_page", fake_read)
    pool = _pool_with("OLD", "OTHER")
    pool.get_page("OLD").jobs_completed = 3
    job_client, pool_client, home_client = FakeClient("OLD"), FakeClient("OLD"), FakeClient("OLD")
    pool.register_client("OLD", pool_client, object())
    logs, saved = [], []
    rows = [UrlRow(id="r1", url="https://arena.ai/c/1", enabled=True, tab_id="OLD"),
            UrlRow(id="r2", url="https://arena.ai/c/2", enabled=True, tab_id="OTHER")]
    bridge = SimpleNamespace(
        state=SimpleNamespace(urls=rows), _auto_scan_running=False, cdp=home_client,
        _log=lambda m, l="info": logs.append((l, m)), _save_arena=lambda: saved.append("arena"),
        _persist_cooldowns=lambda: saved.append("cooldowns"), _emit_pool_status=lambda: None)
    ctx = FinishCtx(pool=pool, bridge=bridge, tab_id="OLD", ctrl=object(), client=job_client)
    return SimpleNamespace(browser=browser, pool=pool, bridge=bridge, ctx=ctx, logs=logs, saved=saved,
                           rows=rows, clients=(job_client, pool_client, home_client))


def _run(ctx, url=NEW_URL):
    return asyncio.run(new_tab.handover(ctx, url, timeout_sec=5))


def test_handover_moves_the_worker_to_a_new_tab_and_closes_the_old(monkeypatch):
    w = _world(monkeypatch)
    ok, why = _run(w.ctx)
    assert ok, why
    assert w.browser.opened == [NEW_URL] and w.browser.closed == ["OLD"]
    assert w.browser.ids == ["OTHER", "NEW1"]              # old tab verified gone
    assert w.ctx.tab_id == "NEW1"
    moved = w.pool.get_page("NEW1")
    assert moved.jobs_completed == 3 and w.pool.get_page("OLD") is None
    assert (w.rows[0].tab_id, w.rows[0].url, w.rows[0].enabled) == ("NEW1", NEW_URL, True)
    assert w.rows[1].tab_id == "OTHER"
    for client in w.clients:                               # every holder moved, none left behind
        assert client._current_tab_id == "NEW1"
    assert {"arena", "cooldowns"} <= set(w.saved)
    assert w.bridge._auto_scan_running is False            # the reconciler is free again
    text = " | ".join(m for _, m in w.logs)
    assert "opening" in text and "old tab closed" in text.lower()


def test_same_new_chat_url_still_closes_the_old_tab(monkeypatch):
    w = _world(monkeypatch)
    w.pool.get_page("OLD").url = NEW_URL
    w.rows[0].url = NEW_URL
    ok, _ = _run(w.ctx)
    assert ok and w.browser.closed == ["OLD"] and "OLD" not in w.browser.ids
    assert any("same" in m.lower() for _, m in w.logs)


def test_a_new_tab_that_is_not_a_new_chat_rolls_back(monkeypatch):
    w = _world(monkeypatch, is_new=(False, "an old chat"))
    ok, why = _run(w.ctx)
    assert not ok and "an old chat" in why
    assert w.browser.closed == ["NEW1"]                    # the new tab closed again, the old one kept
    assert "OLD" in w.browser.ids and w.ctx.tab_id == "OLD"
    assert w.pool.get_page("OLD") is not None and w.rows[0].tab_id == "OLD"
    for client in w.clients:
        assert client._current_tab_id == "OLD"             # every client back home
    assert w.bridge._auto_scan_running is False


def test_a_new_tab_that_never_gets_ready_rolls_back(monkeypatch):
    w = _world(monkeypatch, ready=(False, "timeout waiting for new chat"))
    ok, why = _run(w.ctx)
    assert not ok and "timeout" in why and w.ctx.tab_id == "OLD" and w.browser.closed == ["NEW1"]


def test_a_tab_that_cannot_be_opened_keeps_the_old_one(monkeypatch):
    w = _world(monkeypatch)
    w.browser.open_error = "HTTP 405"
    ok, why = _run(w.ctx)
    assert not ok and "405" in why and w.browser.closed == [] and w.ctx.tab_id == "OLD"


def test_an_old_tab_that_stays_open_is_reported_loudly(monkeypatch):
    w = _world(monkeypatch)
    w.browser.close_ignored = True
    ok, _ = _run(w.ctx)
    assert ok and w.ctx.tab_id == "NEW1"                   # the job moved; only the close failed
    assert w.browser.closed == ["OLD", "OLD"]              # one retry
    assert any(level == "error" and "still open" in m for level, m in w.logs)


def test_a_running_reconcile_pass_means_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.bridge._auto_scan_running = True
    monkeypatch.setattr(new_tab, "_RECONCILE_WAIT_SEC", 0.05)
    ok, why = _run(w.ctx)
    assert not ok and "reconcile" in why and w.browser.opened == []
    assert w.bridge._auto_scan_running is True             # not ours to release


def test_a_tab_not_in_the_pool_means_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.ctx.tab_id = "GONE"
    ok, _ = _run(w.ctx)
    assert not ok and w.browser.opened == []


# ── the post-job seam ───────────────────────────────────────────────────────

def _seam(monkeypatch, *, enabled, handover_result=(True, "moved")):
    from app.services import cooldown_service as cs
    calls = []

    async def fake_handover(ctx, url, timeout_sec):
        calls.append(("handover", url))
        return handover_result
    async def fake_reset(reset_ctx):
        calls.append(("in-place", ""))
        return True, "new chat ready"
    monkeypatch.setattr(new_tab, "handover", fake_handover)
    monkeypatch.setattr(cs, "reset_to_new_chat", fake_reset)
    state = {new_tab.SETTING_KEY: enabled, new_tab.URL_KEY: NEW_URL}
    bridge = SimpleNamespace(config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
                             _cancel_requested=False, _log=lambda *a, **k: None)
    ctx = FinishCtx(pool=None, bridge=bridge, tab_id="OLD", ctrl=object(), client=object())
    return cs, ctx, calls


def test_setting_off_keeps_the_in_place_new_chat(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=False)
    assert asyncio.run(cs._best_effort_reset(ctx, 5))[0]
    assert calls == [("in-place", "")]


def test_setting_on_uses_the_new_tab(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True)
    assert asyncio.run(cs._best_effort_reset(ctx, 5)) == (True, "moved")
    assert calls == [("handover", NEW_URL)]


def test_a_failed_handover_falls_back_to_the_in_place_new_chat(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True, handover_result=(False, "not a new chat"))
    assert asyncio.run(cs._best_effort_reset(ctx, 5))[0]
    assert calls == [("handover", NEW_URL), ("in-place", "")]


def test_firefox_lane_never_opens_tabs(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True)

    async def lane():
        return True, "firefox new chat"
    ctx.lane_reset = lane
    assert asyncio.run(cs._best_effort_reset(ctx, 5)) == (True, "firefox new chat")
    assert calls == []


def test_a_cancelled_run_keeps_the_fast_in_place_reset(monkeypatch):
    cs, ctx, calls = _seam(monkeypatch, enabled=True)
    monkeypatch.setattr(cs, "_is_cancelled", lambda bridge: True)
    asyncio.run(cs._best_effort_reset(ctx, 5))
    assert calls == [("in-place", "")]

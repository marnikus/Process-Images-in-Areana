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
from app.services import new_tab_handover as handover_impl
from app.services import new_tab_identity as identity_impl
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
    """Browser-level Target API and candidate ownership for one endpoint."""
    def __init__(self, *ids, source_context="CTX-MX", candidate_context=None,
                 source_owner="mxxy@example.com", candidate_owners=None):
        self.ids = list(ids)
        self.contexts = {tid: (source_context if tid == "OLD" else "CTX-ANTON") for tid in ids}
        self.owners = {"OLD": source_owner, "OTHER": "anton@example.com"}
        self.candidate_context = candidate_context
        self.candidate_owners = list(candidate_owners or [source_owner])
        self.opened, self.closed, self.create_params = [], [], []
        self.open_error = ""
        self.close_ignored = False

    def send(self, method, params=None):
        params = params or {}
        if method == "Target.getTargets":
            infos = [{"targetId": tid, **({"browserContextId": ctx} if ctx else {})}
                     for tid, ctx in self.contexts.items()]
            return {"result": {"targetInfos": infos}}
        if method == "Target.createTarget":
            self.create_params.append(dict(params))
            if self.open_error:
                raise RuntimeError(self.open_error)
            tid = f"NEW{len(self.opened) + 1}"
            self.opened.append(params["url"])
            self.ids.append(tid)
            context = self.candidate_context
            if context == "source":
                context = self.contexts.get("OLD")
            if context is None and "browserContextId" in params:
                context = params["browserContextId"]
            self.contexts[tid] = context
            self.owners[tid] = self.candidate_owners[0] if self.candidate_owners else ""
            return {"result": {"targetId": tid}}
        raise AssertionError(f"unexpected CDP command: {method}")

    def close(self, host, port, tab_id):
        self.closed.append(tab_id)
        if not self.close_ignored and tab_id in self.ids:
            self.ids.remove(tab_id)
            self.contexts.pop(tab_id, None)
        return True, ""

    def listing(self, host, port, timeout=3.0):
        return [TabInfo(tid, "", NEW_URL, f"ws://{host}:{port}/devtools/page/{tid}")
                for tid in self.ids], "", []


class FakeClient:
    browser = None

    def __init__(self, host="127.0.0.1", port=9333):
        self._host, self._port = host, port
        self._current_tab_id = ""
        self._current_ws_url = ""
        self.moves = []
        self.owner = ""

    async def connect(self, ws_url):
        self._current_ws_url = ws_url
        self.moves.append(ws_url)
        if "/devtools/page/" in ws_url:
            self._current_tab_id = ws_url.rsplit("/", 1)[-1]
        return True

    async def send(self, method, params=None, **kwargs):
        return self.browser.send(method, params)

    async def evaluate(self, expression):
        owner = self.owner or self.browser.owners.get(self._current_tab_id, "")
        if self._current_tab_id.startswith("NEW") and self.browser.candidate_owners:
            owner = self.browser.candidate_owners.pop(0)
        return {"email": owner, "via": "fake"}

    async def disconnect(self):
        return None


def _world(monkeypatch, *, ready=(True, "new chat ready"), is_new=(True, "new chat"),
           candidate_context=None, candidate_owners=None, source_owner="mxxy@example.com",
           source_context="CTX-MX"):
    browser = FakeBrowser("OLD", "OTHER", source_context=source_context,
                          candidate_context=candidate_context, source_owner=source_owner,
                          candidate_owners=candidate_owners)
    monkeypatch.setattr(identity_impl, "fetch_browser_ws_url_sync",
                        lambda host, port: (f"ws://{host}:{port}/devtools/browser/F", ""))
    monkeypatch.setattr(handover_impl, "close_tab_sync", browser.close)
    monkeypatch.setattr(identity_impl, "close_tab_sync", browser.close)
    monkeypatch.setattr(handover_impl, "fetch_tabs_sync", browser.listing)
    monkeypatch.setattr(cdp_tabs, "fetch_tabs_sync", browser.listing)
    monkeypatch.setattr(handover_impl, "GONE_POLL_SEC", 0.01)
    monkeypatch.setattr(handover_impl, "GONE_WAIT_SEC", 0.05)
    monkeypatch.setattr(identity_impl, "IDENTITY_WAIT_SEC", 0.08)
    monkeypatch.setattr(identity_impl, "IDENTITY_POLL_SEC", 0.005)
    monkeypatch.setattr(identity_impl, "CDPClient", FakeClient)
    monkeypatch.setattr(identity_impl, "wait_new_chat_ready", lambda ctx: _async_value(ready))
    monkeypatch.setattr(identity_impl, "read_chat_page", lambda client: _async_value(is_new))
    FakeClient.browser = browser

    pool = _pool_with("OLD", "OTHER")
    pool.get_page("OLD").ws_url = "ws://127.0.0.1:9333/devtools/page/OLD"
    pool.get_page("OLD").jobs_completed = 3
    job_client, pool_client, home_client = (FakeClient() for _ in range(3))
    for client in (job_client, pool_client, home_client):
        client._current_tab_id = "OLD"
        client.owner = source_owner
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


async def _async_value(value):
    return value


def _run(ctx, url=NEW_URL):
    return asyncio.run(new_tab.handover(ctx, url, timeout_sec=5))


def _assert_old_unchanged(w):
    assert w.ctx.tab_id == "OLD" and w.pool.get_page("OLD") is not None
    assert w.rows[0].tab_id == "OLD" and w.bridge._auto_scan_running is False
    for client in w.clients:
        assert client._current_tab_id == "OLD"


def test_handover_moves_only_after_context_new_chat_and_owner_proofs(monkeypatch):
    w = _world(monkeypatch)
    ok, why = _run(w.ctx)
    assert ok, why
    assert w.browser.opened == [NEW_URL] and w.browser.closed == ["OLD"]
    assert w.browser.create_params == [{"url": NEW_URL, "browserContextId": "CTX-MX"}]
    assert w.browser.ids == ["OTHER", "NEW1"] and w.ctx.tab_id == "NEW1"
    moved = w.pool.get_page("NEW1")
    assert moved.jobs_completed == 3 and moved.owner == "mxxy@example.com"
    assert (w.rows[0].tab_id, w.rows[0].url, w.rows[0].enabled) == ("NEW1", NEW_URL, True)
    assert w.rows[1].tab_id == "OTHER"
    for client in w.clients:
        assert client._current_tab_id == "NEW1"
    assert {"arena", "cooldowns"} <= set(w.saved)
    assert any("stable owner=mxxy@example.com" in m for _, m in w.logs)
    assert not any("Network.getAllCookies" in str(x) or "Network.setCookie" in str(x)
                   for x in w.browser.create_params)


def test_default_context_is_proved_and_create_target_omits_optional_context(monkeypatch):
    w = _world(monkeypatch, source_context=None, candidate_context=None)
    ok, why = _run(w.ctx)
    assert ok, why
    assert w.browser.create_params == [{"url": NEW_URL}]
    assert w.ctx.tab_id == "NEW1"


def test_same_new_chat_url_still_closes_the_old_tab(monkeypatch):
    w = _world(monkeypatch)
    w.pool.get_page("OLD").url = NEW_URL
    w.rows[0].url = NEW_URL
    ok, _ = _run(w.ctx)
    assert ok and w.browser.closed == ["OLD"] and "OLD" not in w.browser.ids


@pytest.mark.parametrize("kwargs,reason", [
    ({"candidate_context": "CTX-ANTON"}, "context mismatch"),
    ({"candidate_owners": ["anton@example.com"]}, "owner mismatch"),
    ({"candidate_owners": [""]}, "not stably proven"),
    ({"source_owner": ""}, "source Arena account is unknown"),
])
def test_unknown_or_mismatched_identity_closes_only_candidate(monkeypatch, kwargs, reason):
    w = _world(monkeypatch, **kwargs)
    ok, why = _run(w.ctx)
    assert not ok and reason.lower() in why.lower()
    assert w.browser.closed == ([] if "source_owner" in kwargs else ["NEW1"])
    _assert_old_unchanged(w)


def test_unreadable_source_context_fails_before_opening_candidate(monkeypatch):
    w = _world(monkeypatch)
    w.browser.contexts.pop("OLD")
    ok, why = _run(w.ctx)
    assert not ok and "source target context" in why
    assert w.browser.opened == [] and w.browser.closed == []
    _assert_old_unchanged(w)


def test_a_new_tab_that_is_not_a_new_chat_rolls_back(monkeypatch):
    w = _world(monkeypatch, is_new=(False, "an old chat"))
    ok, why = _run(w.ctx)
    assert not ok and "an old chat" in why
    assert w.browser.closed == ["NEW1"]
    _assert_old_unchanged(w)


def test_a_new_tab_that_never_gets_ready_rolls_back(monkeypatch):
    w = _world(monkeypatch, ready=(False, "timeout waiting for new chat"))
    ok, why = _run(w.ctx)
    assert not ok and "timeout" in why
    assert w.browser.closed == ["NEW1"]
    _assert_old_unchanged(w)


def test_target_creation_failure_keeps_the_old_one(monkeypatch):
    w = _world(monkeypatch)
    w.browser.open_error = "Target.createTarget refused"
    ok, why = _run(w.ctx)
    assert not ok and "refused" in why and w.browser.closed == []
    _assert_old_unchanged(w)


def test_an_old_tab_that_stays_open_is_reported_loudly(monkeypatch):
    w = _world(monkeypatch)
    w.browser.close_ignored = True
    ok, _ = _run(w.ctx)
    assert ok and w.ctx.tab_id == "NEW1"
    assert w.browser.closed.count("OLD") == 2
    assert any(level == "error" and "verification failed" in m for level, m in w.logs)


def test_a_running_reconcile_pass_means_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.bridge._auto_scan_running = True
    monkeypatch.setattr(handover_impl, "RECONCILE_WAIT_SEC", 0.02)
    ok, why = _run(w.ctx)
    assert not ok and "reconcile" in why and w.browser.opened == []
    assert w.bridge._auto_scan_running is True


def test_a_tab_not_in_the_pool_means_no_handover(monkeypatch):
    w = _world(monkeypatch)
    w.ctx.tab_id = "GONE"
    ok, _ = _run(w.ctx)
    assert not ok and w.browser.opened == []


def test_handover_uses_validated_source_endpoint_not_primary_connection(monkeypatch):
    w = _world(monkeypatch)
    w.ctx.client._host = w.pool.get_clients("OLD")[0]._host = "127.0.0.1"
    w.ctx.client._port = w.pool.get_clients("OLD")[0]._port = 9334
    w.pool.get_page("OLD").ws_url = "ws://localhost:9334/devtools/page/OLD"
    w.bridge.cdp._port = 9222
    FakeClient.browser = w.browser
    # Browser-level websocket discovery and target listing must use the old page endpoint.
    seen = []
    monkeypatch.setattr(identity_impl, "fetch_browser_ws_url_sync",
                        lambda host, port: (seen.append((host, port)) or f"ws://{host}:{port}/devtools/browser/F", ""))
    ok, why = _run(w.ctx)
    assert ok, why
    assert seen == [("127.0.0.1", 9334)]
    assert w.ctx.tab_id == "NEW1"


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

"""D4.3-ext: browser_tabs + page_pool panel slots and phase functions.

RULE 8: real PagePool/CDPClient (fake websockets from conftest); the "Chrome"
tab list is faked per test. Slots are exercised through mixin hosts; async
phase functions are driven directly or by awaiting the captured schedule_coro.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import UrlRow
from app.persistence.config_manager import ConfigManager
from app.ui.panels import browser_tabs as bt_mod
from app.ui.panels import page_pool as pp_mod
from app.ui.panels.browser_tabs import BrowserTabsMixin
from app.ui.panels.page_pool import (
    PagePoolMixin,
    do_connect_page_pool,
    reset_pool_dicts,
)
from app.ui.qt_compat import Signal

from tests.conftest import make_client
from tests.test_panel_slots import make_host

pytestmark = pytest.mark.unit


def tab(id_, title="Arena", url="https://arena.ai/c", ws=None):
    return SimpleNamespace(id=id_, title=title, url=url,
                           ws_url=ws or f"ws://127.0.0.1:9222/devtools/page/{id_}",
                           type="page")


def fake_fetch(tabs):
    async def _fetch(self=None):
        return tabs
    return _fetch


def diag_payload(tabs=(), port_open=True):
    return {
        "host": "127.0.0.1", "port": 9222,
        "checks": [{"host": "127.0.0.1", "port_open": port_open, "version": {"Browser": "1"},
                    "list_count": len(tabs), "tabs": [{"title": t.title, "url": t.url, "id": t.id}
                                                       for t in tabs[:10]]}],
        "tabs": [{"title": t.title, "url": t.url, "ws_url": t.ws_url, "id": t.id} for t in tabs],
        "summary": "✅ Found 1 unique tab" if tabs else "⚠ no tabs",
    }


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)

    def connect(self, *args, **kwargs):
        pass


def make_bridge(cdp, config, urls=(), pool=None, **extra):
    from app.ui.panels.page_pool import do_connect_page_pool  # noqa: F401 (sibling check)
    logs = []
    host = SimpleNamespace(
        cdp=cdp, config=config,
        state=SimpleNamespace(urls=list(urls), images=[], recalculate_progress=lambda: None),
        _page_pool=pool if pool is not None else PagePool(),
        _log=lambda msg, level="info": logs.append((level, msg)),
        logs=logs,
        _save_arena=lambda: None,
        _emit_arena_state=lambda: None,
        _emit_pool_status=lambda: None,
        _persist_cooldowns=lambda: None,
        connection_status=Emitter(), tab_match_result=Emitter(),
        tabs_received=Emitter(), page_pool_updated=Emitter(),
        _last_connect_ws="", _last_connect_ts=0.0, _connect_in_progress=False,
        _last_find_query="", _last_find_ts=0.0, _find_in_progress=False,
        _auto_scan_running=False, _ensure_running=False, _run_state="idle",
    )
    for key, value in extra.items():
        setattr(host, key, value)
    return host


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def schedule_capture(monkeypatch):
    queued = []
    monkeypatch.setattr(bt_mod, "schedule_coro", lambda bridge, coro: queued.append(coro))
    return queued


# ── page_pool module functions ──

async def test_reset_pool_dicts():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/1", title="A", url="u"))
    pool.register_client("t1", object(), object())
    assert pool.get_page("t1") is not None
    reset_pool_dicts(pool)
    assert pool.get_page("t1") is None
    assert pool._clients == {} and pool._controllers == {}


async def test_clear_time_paths(cfg):
    """Clear time (D-5) freed the stale page the old `reset_stuck_page` refused:
    the run decides liveness, not a leftover `current_image` (round 2026-09-21)."""
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/1", title="A", url="u"))
    bridge, _logs = make_host((PagePoolMixin,), _page_pool=pool, config=cfg,
                              page_pool_updated=Emitter(), _log=lambda m, l="info": None,
                              _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)
    page = pool.get_page("t1")
    page.status = PageStatus.BUSY  # stale: no run owns this tab any more
    reply = json.loads(bridge.reset_page_cooldown("t1"))
    assert reply["ok"] is True and reply["job_cleared"] is True
    assert page.status == PageStatus.STEADY and page.current_image is None
    # a live job keeps its page — only its countdown is cleared
    page.status = PageStatus.BUSY
    page.current_image = "i1.png"
    bridge._batch_future = SimpleNamespace(done=lambda: False)
    reply = json.loads(bridge.reset_page_cooldown("t1"))
    assert reply == {"ok": True, "was": 0, "busy": True, "job_cleared": False}
    assert page.current_image == "i1.png" and page.status == PageStatus.BUSY
    assert json.loads(bridge.reset_page_cooldown("ghost"))["ok"] is False


async def test_do_connect_page_pool_success_and_failure(cdp_server, cfg):
    pool = PagePool()
    bridge = make_bridge(cdp=None, config=cfg, pool=pool)
    await do_connect_page_pool(bridge, "ws://127.0.0.1:9222/devtools/page/t9")
    page = pool.get_page("t9")
    assert page is not None and page.status == PageStatus.STEADY
    assert pool.get_clients("t9")[0] is not None  # dedicated client registered
    # refused connect → no page, error logged
    cdp_server.reject = True
    await do_connect_page_pool(bridge, "ws://127.0.0.1:9222/devtools/page/tX")
    assert pool.get_page("tX") is None
    assert any("Pool connect failed" in msg for _, msg in bridge.logs)
    cdp_server.reject = False


# ── page_pool slots ──

def test_pool_slots_status_clear_disconnect(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/1", title="A", url="u"))
    host, _ = make_host((PagePoolMixin,), _page_pool=pool, config=cfg,
                        page_pool_updated=Emitter(), _log=lambda m, l="info": None,
                        _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)
    snap = json.loads(host.get_page_pool_status())
    assert snap["total"] == 1 and any(c == (json.dumps(snap, ensure_ascii=False),)
                                      for c in host.page_pool_updated.calls)
    assert json.loads(host.clear_page_pool())["cleared"] == 1
    assert pool.get_page("t1") is None
    pool.add_page(PageInfo(tab_id="t2", ws_url="ws://x/2", title="B", url="u"))
    assert json.loads(host.disconnect_page_pool("t2"))["ok"] is True
    assert json.loads(host.disconnect_page_pool("t2"))["error"] == "not found"
    empty = make_host((PagePoolMixin,), _page_pool=None, config=cfg,
                      page_pool_updated=Emitter(), _log=lambda m, l="info": None,
                      _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)[0]
    assert json.loads(empty.get_page_pool_status())["total"] == 0
    assert json.loads(empty.clear_page_pool())["cleared"] == 0
    assert json.loads(empty.disconnect_page_pool("t"))["error"] == "pool not initialized"


def test_pool_slots_connect_and_cooldowns(cfg, monkeypatch):
    pool = PagePool()
    queued = []
    # L-6 de-masked: spy on the real seam, no private scheduler on the host
    monkeypatch.setattr(pp_mod, "schedule_coro", lambda bridge, coro: queued.append(coro))
    host, _ = make_host((PagePoolMixin,), _page_pool=pool, config=cfg,
                        page_pool_updated=Emitter(), _log=lambda m, l="info": None,
                        _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)
    assert json.loads(host.connect_page_pool(""))["error"] == "empty ws_url"
    assert json.loads(host.connect_page_pool("ws://127.0.0.1:9222/devtools/page/t1"))["ok"] is True
    assert len(queued) == 1
    queued[0].close()
    assert json.loads(host.get_cooldown_config())["ok"] is True
    set_reply = json.loads(host.set_cooldown_config(json.dumps(
        {"enabled": True, "min_seconds": 60, "captcha_penalty_seconds": 4,
         "rate_limit_penalty_seconds": 3})))
    assert set_reply["ok"] is True and set_reply["config"]["min_seconds"] == 60
    bad_reply = json.loads(host.set_cooldown_config(json.dumps({"min_seconds": "abc"})))
    assert bad_reply["config"]["min_seconds"] == 300  # non-numeric → default
    # page lifecycle for cooldown control
    pool.add_page(PageInfo(tab_id="tc", ws_url="ws://x/c", title="C", url="u"))
    page = pool.get_page("tc")
    page.status = PageStatus.COOLDOWN  # plain cooldown → reset_cooldown path
    assert json.loads(host.reset_page_cooldown("tc"))["ok"] is True
    assert page.status == PageStatus.STEADY
    page.status = PageStatus.BUSY  # stuck → force-reset path
    assert json.loads(host.reset_page_cooldown("tc"))["ok"] is True
    assert page.status == PageStatus.STEADY
    assert json.loads(host.set_page_cooldown("tc", 3600))["ok"] is True
    assert json.loads(host.set_page_cooldown("ghost", 60))["ok"] is False
    assert json.loads(host.reset_page_cooldown("ghost"))["error"] == "unknown tab"


def test_pool_stop_tab_job(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="tj", ws_url="ws://x/j", title="J", url="u"))
    host, _ = make_host((PagePoolMixin,), _page_pool=pool, config=cfg,
                        page_pool_updated=Emitter(), _log=lambda m, l="info": None,
                        _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)
    assert json.loads(host.stop_tab_job("tj"))["error"] == "no live job on this tab"
    pool.get_page("tj").current_image = "img.png"
    assert json.loads(host.stop_tab_job("tj"))["ok"] is True
    assert json.loads(host.stop_tab_job("ghost"))["ok"] is False


# ── browser_tabs: debounce / identity / pool-join ──

async def test_claim_connect_slot_debounce(cfg):
    bridge = make_bridge(cdp=None, config=cfg)
    assert claim_ok(bridge, "ws://a/1") is True
    assert claim_ok(bridge, "ws://a/1") is False  # <1.5s same url
    bridge._last_connect_ts = time.time() - 2
    assert claim_ok(bridge, "ws://a/1") is True
    bridge._connect_in_progress = True
    bridge._last_connect_ts = time.time() - 2
    assert claim_ok(bridge, "ws://a/1") is False  # in progress
    assert claim_ok(bridge, "ws://b/2") is True  # different url allowed


def claim_ok(bridge, ws):
    return bt_mod.claim_connect_slot(bridge, ws)


async def test_connect_reused_and_identity(cfg):
    from app.browser.cdp_client import CDPClient
    client = CDPClient()
    bridge = make_bridge(cdp=client, config=cfg)
    assert await bt_mod.connect_reused(bridge, "ws://x/1") is False  # not connected
    client._connected = True
    client._ws = object()  # is_connected needs both flags
    client._current_tab_id = "tA"
    assert await bt_mod.connect_reused(bridge, "ws://x/devtools/page/tA") is True
    assert bridge.connection_status.calls and bridge.connection_status.calls[-1] == ("connected",)
    assert await bt_mod.connect_reused(bridge, "ws://x/devtools/page/tB") is False
    client._current_title, client._current_url = "Title A", "https://arena.ai/c"
    ident = bt_mod.cached_tab_identity(bridge, "ws://x/tA")
    assert ident == ("tA", "Title A", "https://arena.ai/c")
    assert await bt_mod.pool_tab_identity(bridge, "ws://x/tA") == ident


async def test_pool_join_paths(cdp_server, cfg):
    pool = PagePool()
    client = make_client(cdp_server)
    bridge = make_bridge(cdp=client, config=cfg, pool=pool)
    # fallback join registers the primary client (sync helper)
    bt_mod.add_fallback_pool_page(bridge, ("t1", "ws://127.0.0.1:9222/devtools/page/t1",
                                           "A", "https://arena.ai/c"))
    page = pool.get_page("t1")
    assert page is not None and pool.get_clients("t1")[0] is client
    # dedicated join: fresh per-tab client
    await bt_mod.add_dedicated_pool_page(bridge, ("t2", "ws://127.0.0.1:9222/devtools/page/t2",
                                                  "B", "https://arena.ai/c"))
    assert pool.get_clients("t2")[0] is not client
    assert any("2 tabs in pool" in msg for _, msg in bridge.logs)
    # reuse: existing connected client → no new client
    bt_mod.reuse_pool_page(bridge, ("t1", "ws://127.0.0.1:9222/devtools/page/t1",
                                    "A2", "https://arena.ai/c"))
    assert pool.get_clients("t1")[0] is client
    # attach routing
    await bt_mod.attach_connected_tab(bridge, "ws://127.0.0.1:9222/devtools/page/t2")
    assert pool.get_clients("t2")[0] is pool.get_clients("t2")[0]  # stable (reuse)
    no_pool = make_bridge(cdp=client, config=cfg, pool=None)
    await bt_mod.attach_connected_tab(no_pool, "ws://x/9")  # no-op


async def test_do_connect_tab_success_reuse_and_failure(cdp_server, cfg):
    pool = PagePool()
    client = make_client(cdp_server)
    client._current_title, client._current_url = "T", "https://arena.ai/c"
    bridge = make_bridge(cdp=client, config=cfg, pool=pool)
    ws = "ws://127.0.0.1:9222/devtools/page/t1"
    await bt_mod.do_connect_tab(bridge, ws)
    assert client.is_connected and pool.get_page("t1") is not None
    assert bridge._connect_in_progress is False
    # reuse: same tab again → no second connection
    connects = len(cdp_server.connects)
    await bt_mod.do_connect_tab(bridge, ws)
    assert len(cdp_server.connects) == connects
    # failure: all candidates rejected
    fresh = make_client(cdp_server)
    bridge2 = make_bridge(cdp=fresh, config=cfg, pool=PagePool())
    cdp_server.reject = True
    await bt_mod.do_connect_tab(bridge2, "ws://127.0.0.1:9222/devtools/page/tF")
    cdp_server.reject = False
    assert not fresh.is_connected
    assert bridge2.connection_status.calls[-1] == ("error",)
    assert any("Connect failed" in msg for _, msg in bridge2.logs)


# ── browser_tabs: find / fetch / diagnose ──

async def test_claim_find_slot_and_dupe(cfg):
    bridge = make_bridge(cdp=None, config=cfg)
    assert bt_mod.claim_find_slot(bridge, " arena.ai ") == "arena.ai"
    assert bt_mod.claim_find_slot(bridge, "arena.ai") is None  # 1s debounce
    bridge._last_find_ts = time.time() - 2
    assert bt_mod.claim_find_slot(bridge, "arena.ai") == "arena.ai"
    bridge._find_in_progress = True
    bridge._last_find_ts = time.time() - 2
    assert bt_mod.claim_find_slot(bridge, "arena.ai") is None
    assert bt_mod.find_dupe_recent(bridge, "", time.time()) is False


async def test_find_tab_paths(cdp_server, cfg):
    from app.browser.cdp_client import CDPClient
    client = CDPClient()
    all_tabs = [tab("t1", "Arena Image", "https://arena.ai/c/direct"),
                tab("t2", "Docs", "https://docs.example.com")]
    client.fetch_tabs = fake_fetch(all_tabs)
    client.diagnose_sync = lambda: diag_payload()
    bridge = make_bridge(cdp=client, config=cfg)
    # empty query (do_find_tab strips before answering)
    await bt_mod.do_find_tab(bridge, "   ")
    assert bridge.tab_match_result.calls[-1] == ("", "[]")
    # match found
    await bt_mod.do_find_tab(bridge, "arena.ai")
    matches = json.loads(bridge.tab_match_result.calls[-1][1])
    assert any(m["id"] == "t1" for m in matches)
    assert any("match" in msg for _, msg in bridge.logs)
    # no match
    await bt_mod.do_find_tab(bridge, "zzz-no-such-thing-12345")
    assert bridge.tab_match_result.calls[-1][1] == "[]"
    # no tabs at all → diagnose summary
    client.fetch_tabs = fake_fetch([])
    await bt_mod.match_live_tabs(bridge, "arena.ai")
    assert bridge.tab_match_result.calls[-1][1] == "[]"
    assert any("Fix:" in msg for _, msg in bridge.logs)
    # fetch raises → reported, still answers []
    async def boom():
        raise RuntimeError("net down")
    client.fetch_tabs = boom
    await bt_mod.do_find_tab(bridge, "arena.ai")
    assert bridge.tab_match_result.calls[-1][1] == "[]"
    assert bridge._find_in_progress is False


async def test_fetch_tabs_slot_and_diagnose(cdp_server, cfg, monkeypatch):
    from app.browser.cdp_client import CDPClient
    queued = schedule_capture(monkeypatch)
    client = CDPClient()
    tabs = [tab("t1", "Arena", "https://arena.ai/c")]
    client.fetch_tabs = fake_fetch(tabs)
    client.diagnose_sync = lambda: diag_payload(tabs)
    logs = []
    host, _ = make_host((BrowserTabsMixin,), cdp=client, config=cfg,
                        _page_pool=None, _log=lambda m, l="info": logs.append((l, m)),
                        logs=logs, _auto_scan_running=False, tabs_received=Emitter(),
                        connection_status=Emitter())
    assert host.get_tabs() == "pending" and len(queued) == 1
    await queued.pop()
    payload = json.loads(host.tabs_received.calls[-1][0])
    assert payload[0]["id"] == "t1"
    assert host.diagnose_chrome() == "pending"
    await queued.pop()
    assert any("open" in msg for _, msg in logs)
    # empty list also logs the diagnose summary
    client.fetch_tabs = fake_fetch([])
    host.get_tabs()
    await queued.pop()
    assert host.tabs_received.calls[-1][0] == "[]"
    # guards: no cdp
    none_host = make_host((BrowserTabsMixin,), cdp=None, config=cfg, _page_pool=None,
                          _log=lambda m, l="info": None, _auto_scan_running=False,
                          tabs_received=Emitter(), connection_status=Emitter())[0]
    assert json.loads(none_host.get_tabs()) == []
    assert json.loads(none_host.diagnose_chrome())["error"] == "CDP not available"


async def test_popup_and_primary_guards(cfg, monkeypatch):
    """Popup: no targets warns; raise failure counts 0. Primary: a broken pool answers '' and the tick never raises."""
    bridge = make_bridge(cdp=None, config=cfg)
    await bt_mod.do_popup_url_tabs(bridge)
    assert any("no active URL tabs" in m for _, m in bridge.logs)
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/t1", title="Arena", url="https://arena.ai", is_connected=True))
    bridge = make_bridge(cdp=None, config=cfg, pool=pool, urls=[UrlRow.create("https://arena.ai", tab_id="t1")])
    monkeypatch.setattr(bt_mod, "raise_window_titles", lambda titles: (_ for _ in ()).throw(RuntimeError("no desktop")))
    await bt_mod.do_popup_url_tabs(bridge)
    assert any("0/1 windows" in m for _, m in bridge.logs)
    bridge._page_pool = SimpleNamespace(_pages=None)  # `.values()` on None → guarded ''
    assert bt_mod.primary_ws(bridge) == ""
    bridge.cdp = SimpleNamespace(is_connected=False)
    bridge._ensure_running = False
    await bt_mod.do_ensure_primary(bridge)  # ws '' → nothing to connect, no exception
    assert bridge._ensure_running is False
    host = make_host((BrowserTabsMixin,), cdp=None, _page_pool=None)[0]
    assert json.loads(host.popup_url_tabs())["error"] == "pool not initialized"
    assert json.loads(host.ensure_primary_connected()) == {"ok": False}


def test_live_deps_wires_the_ui_seam(cfg):
    """S6: the reconciler's callables come from ui land — fetch via cdp, join via the pool, commit without undo.

    I-64: the fetch is Chrome's own listing merged with the Firefox discovery, and
    the join routes a Firefox id to the id join (both bound to this bridge).
    """
    from app.services.live.reconcile import LiveDeps
    from app.ui.services import firefox_pool
    bridge = make_bridge(cdp=None, config=cfg)
    deps = bt_mod.live_deps(bridge)
    assert isinstance(deps, LiveDeps) and deps.log is bridge._log
    assert deps.commit.func.__name__ == "commit_urls_system"
    assert deps.fetch_tabs.func is firefox_pool.merged_listing and deps.fetch_tabs.args[0] is bridge
    assert deps.fetch_tabs.args[1].func is bt_mod.reconcile_tabs      # Chrome's half stays the panel's listing
    assert deps.join_tab.func is firefox_pool.join_any and deps.join_tab.args == (bridge,)


async def test_auto_scan_pass_end_to_end(cdp_server, cfg):
    pool = PagePool()
    client = make_client(cdp_server)
    client.fetch_tabs = fake_fetch([tab("t1", "A", "https://arena.ai/c/direct"),
                                    tab("t2", "B", "https://other.example.com/x")])
    bridge = make_bridge(cdp=client, config=cfg, pool=pool)
    await bt_mod.auto_scan_pass(bridge, "manual")
    # arena.ai row added + pool joined; non-matching tab ignored
    assert any(u.url == "https://arena.ai/c/direct" for u in bridge.state.urls)
    assert pool.get_page("t1") is not None and pool.get_page("t2") is None
    assert any("Reconcile:" in msg for _, msg in bridge.logs)
    # second manual scan (D-2, 2026-09-21): Reparse sweeps first — the row is rebuilt with a fresh id
    first_id = bridge.state.urls[0].id
    await bt_mod.auto_scan_pass(bridge, "manual")
    assert any("🧹 Reparse: cleared 1 URL row(s)" in msg for _, msg in bridge.logs)
    assert len(bridge.state.urls) == 1 and bridge.state.urls[0].id != first_id
    assert pool.get_page("t1") is not None and pool.get_page("t2") is None  # pool presence kept
    # busy guard + exception path (the pass owns the `_auto_scan_running` flag)
    bridge._auto_scan_running = True
    await bt_mod.auto_scan_pass(bridge, "auto")  # no-op
    assert bridge._auto_scan_running is True
    bridge._auto_scan_running = False

    async def boom():
        raise RuntimeError("scan down")
    client.fetch_tabs = boom
    await bt_mod.auto_scan_pass(bridge, "auto")
    assert bridge._auto_scan_running is False
    assert any("Reconcile skipped" in msg for _, msg in bridge.logs)
    assert len(bridge.state.urls) == 1  # a failed fetch never removes


# ── browser_tabs: popup / primary / slots ──

async def test_popup_targets_and_do_popup(cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/1", title="Win A", url="u"))
    pool.add_page(PageInfo(tab_id="t2", ws_url="ws://x/2", title="Win B", url="u"))
    pool.get_page("t2").is_connected = False
    rows = [UrlRow.create("https://arena.ai/c/a", tab_id="t1", enabled=True),
            UrlRow.create("https://arena.ai/c/b", tab_id="t1", enabled=True),  # dupe tab
            UrlRow.create("https://arena.ai/c/c", tab_id="t2", enabled=True),  # not connected
            UrlRow.create("https://arena.ai/c/d", enabled=False)]
    bridge = make_bridge(cdp=None, config=cfg, pool=pool, urls=rows)
    titles = bt_mod.popup_targets(bridge)
    assert titles == ["Win A"]  # deduped, connected only
    await bt_mod.do_popup_url_tabs(bridge)
    # non-win32 raises no windows: 0/1, tabs untouched
    assert any("0/1 windows on top" in msg for _, msg in bridge.logs)
    empty = make_bridge(cdp=None, config=cfg, pool=PagePool(), urls=rows)
    await bt_mod.do_popup_url_tabs(empty)
    assert any("no active URL tabs" in msg for _, msg in empty.logs)


async def test_primary_ws_and_ensure_primary(cdp_server, cfg):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://127.0.0.1:9222/devtools/page/t1",
                           title="A", url="u"))
    client = make_client(cdp_server)
    bridge = make_bridge(cdp=client, config=cfg, pool=pool)
    assert bt_mod.primary_ws(bridge) == "ws://127.0.0.1:9222/devtools/page/t1"
    assert bt_mod.primary_ws(make_bridge(cdp=client, config=cfg, pool=None)) == ""
    # down → passive connect
    await bt_mod.do_ensure_primary(bridge)
    assert client.is_connected is True
    assert bridge.connection_status.calls[-1] == ("connected",)
    # already connected → no-op
    connects = len(cdp_server.connects)
    await bt_mod.do_ensure_primary(bridge)
    assert len(cdp_server.connects) == connects


def test_browser_tab_slot_guards(cfg, monkeypatch):
    queued = schedule_capture(monkeypatch)
    client = make_client()
    client._connected = True
    client._ws = object()  # ensure_primary short-circuit
    host, _ = make_host((BrowserTabsMixin,), cdp=client, config=cfg, _page_pool=None,
                        _log=lambda m, l="info": None, _auto_scan_running=False,
                        _last_connect_ws="", _last_connect_ts=0.0, _connect_in_progress=False,
                        _last_find_query="", _last_find_ts=0.0, _find_in_progress=False,
                        tabs_received=Emitter(), connection_status=Emitter())
    assert host.ensure_primary_connected() == json.dumps({"ok": True})
    host.connect_tab("ws://127.0.0.1:9222/devtools/page/t1")
    assert len(queued) == 1
    host.connect_tab("ws://127.0.0.1:9222/devtools/page/t1")  # debounced → nothing new
    assert len(queued) == 1
    host.find_tab_by_url("arena.ai")
    assert len(queued) == 2
    host.find_tab_by_url("arena.ai")  # debounced
    assert len(queued) == 2
    assert host.auto_connect_scan("manual") == json.dumps({"ok": False, "error": "CDP or pool not ready"})
    assert host.popup_url_tabs() == json.dumps({"ok": False, "error": "pool not initialized"})
    none_host = make_host((BrowserTabsMixin,), cdp=None, config=cfg, _page_pool=None,
                          _log=lambda m, l="info": None, _auto_scan_running=False,
                          tabs_received=Emitter(), connection_status=Emitter())[0]
    none_host.connect_tab("ws://x")  # logged, no schedule
    none_host.find_tab_by_url("q")
    assert len(queued) == 2
    # with pool: auto scan schedules; running → "pending"
    from app.ui.panels.page_pool import do_connect_page_pool  # noqa: F401
    pool_host = make_host((BrowserTabsMixin,), cdp=client, config=cfg, _page_pool=PagePool(),
                          _log=lambda m, l="info": None, _auto_scan_running=False,
                          _last_connect_ws="", _last_connect_ts=0.0, _connect_in_progress=False,
                          _last_find_query="", _last_find_ts=0.0, _find_in_progress=False,
                          tabs_received=Emitter(), connection_status=Emitter())[0]
    assert pool_host.auto_connect_scan("manual") == "pending" and len(queued) == 3
    pool_host._auto_scan_running = True
    assert pool_host.auto_connect_scan("auto") == "pending" and len(queued) == 3
    queued.clear()
    # primary down → schedules ensure
    client._connected = False
    assert pool_host.ensure_primary_connected() == "pending" and len(queued) == 1
    coro = queued.pop()
    assert coro.cr_frame is not None
    coro.close()


# ── scan seam + connect-path helpers ──

def test_scan_targets_follows_settings(monkeypatch, cfg):
    from app.browser.browsers import ScanNote  # noqa: F401 (sibling import check)
    bridge = make_bridge(cdp=None, config=cfg)
    cfg.set_state(cdp_browsers={"chrome": {"enabled": False}})
    assert bt_mod.scan_targets(bridge) == ([], [])
    cfg.set_state(cdp_browsers={})
    monkeypatch.setattr("app.browser.cdp.fetch_tabs_sync",
                        lambda host, port, timeout=3.0: ([tab("t1")], "", ["http"]))
    rows, notes = bt_mod.scan_targets(bridge)
    assert [r.id for r in rows] == ["t1"] and notes == []
    monkeypatch.setattr("app.browser.cdp.fetch_tabs_sync",
                        lambda host, port, timeout=3.0: ([], "connection refused", ["http"]))
    rows, notes = bt_mod.scan_targets(bridge)
    assert rows == [] and len(notes) == 1 and notes[0].reason == "connection refused"


def test_scan_settings_fallback_without_config():
    rows, base, host = bt_mod.scan_settings(SimpleNamespace(cdp=None))
    assert rows == {} and base == 9222 and host == "127.0.0.1"


def test_report_scan_notes_logs_each_reason_once(cfg):
    from app.browser.browsers import ScanNote
    bridge = make_bridge(cdp=None, config=cfg)
    note = ScanNote(browser="chrome", host="127.0.0.1", port=9222,
                    reason="down", protocol="http")
    bt_mod.report_scan_notes(bridge, [note])
    bt_mod.report_scan_notes(bridge, [note])       # same reason → silent
    downs = sum("chrome: down" in m for _lvl, m in bridge.logs)
    assert downs == 1
    bt_mod.report_scan_notes(bridge, [])           # recovered → reason dropped
    bt_mod.report_scan_notes(bridge, [note])       # fails again → logged again
    assert sum("chrome: down" in m for _lvl, m in bridge.logs) == 2


def test_pool_page_for_and_announce(cfg):
    bridge = make_bridge(cdp=SimpleNamespace(_current_tab_id="t1", _host="127.0.0.1",
                                             _port=9222), config=cfg)
    row = bt_mod.pool_page_for(bridge, ("t1", "ws://127.0.0.1:9222/devtools/page/t1",
                                        "Arena", "https://arena.ai/c"))
    assert isinstance(row, PageInfo) and row.tab_id == "t1"
    bt_mod.announce_tab_connected(bridge, "ws://127.0.0.1:9222/devtools/page/t1")
    assert bridge.connection_status.calls == [("connected",)]
    assert any(lvl == "success" for lvl, _m in bridge.logs)


async def test_report_no_tabs_survives_diagnose_failure(cfg):
    def boom():
        raise RuntimeError("diagnose down")

    bridge = make_bridge(cdp=SimpleNamespace(diagnose_sync=boom, _host="127.0.0.1",
                                             _port=9222), config=cfg)
    await bt_mod.report_no_tabs(bridge, "arena")
    assert bridge.tab_match_result.calls == [("arena", "[]")]
    assert any(lvl == "warn" and "No Chrome tabs found" in m for lvl, m in bridge.logs)


async def test_merge_rows_and_active_client_rows(cfg):
    bridge = make_bridge(cdp=SimpleNamespace(fetch_tabs=fake_fetch([tab("t2")])), config=cfg)
    merged = bt_mod.merge_rows([tab("t1")], [tab("t1"), tab("t2"), SimpleNamespace(id="", tab_id="", title="", url="", ws_url="")])
    assert [r.id for r in merged] == ["t1", "t2", ""]   # dupe skipped, keyless kept
    rows = await bt_mod.active_client_rows(bridge)
    assert [r.id for r in rows] == ["t2"]
    assert await bt_mod.active_client_rows(make_bridge(cdp=None, config=cfg)) == []

    async def boom():
        raise RuntimeError("x")

    bad = make_bridge(cdp=SimpleNamespace(fetch_tabs=boom), config=cfg)
    assert await bt_mod.active_client_rows(bad) == []


def test_base_port_and_claim_guards(cfg):
    assert bt_mod._base_port("junk") == 9222       # int() blows up → default
    assert bt_mod._base_port(0) == 9222            # out of range → default
    assert bt_mod._base_port(9333) == 9333
    bridge = make_bridge(cdp=None, config=cfg)
    bridge._last_find_ts = "junk"                  # dupe-check arithmetic blows up
    assert bt_mod.claim_find_slot(bridge, " arena ") == "arena"   # except fallback


async def test_live_tab_rows_scan_failure_and_fallback(cfg, monkeypatch):
    bridge = make_bridge(cdp=SimpleNamespace(fetch_tabs=fake_fetch([tab("t9")])), config=cfg)

    def explode(_bridge):
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(bt_mod, "scan_targets", explode)
    assert await bt_mod.live_tab_rows(bridge) == []
    assert "scan blew up" in bridge._scan_failed

    monkeypatch.setattr(bt_mod, "scan_targets", lambda _b: ([], []))
    rows = await bt_mod.live_tab_rows(bridge)
    assert [r.id for r in rows] == ["t9"]          # client's own list is the last resort
    assert bridge._scan_failed == ""

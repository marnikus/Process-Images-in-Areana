"""Pool & UI seams — conn fields, the Firefox join, rejoin routing (D-5/D-10).

`page_status`/`page_pool` own the browser fields the whole app reads; the
pool panel's `join_discovered_page` is the one entry point a discovered
Firefox tab gets (page only — no socket); the browser_tabs panel merges the
two fetches behind `DISCOVERY_ENABLED` (off in every test, see conftest).
"""

import json
from types import SimpleNamespace

import pytest

from app.browser import page_status as ps
from app.browser.page_pool import PagePool, discovered_page_info
from app.browser.uivision.discovery import FirefoxTab
from app.core.browser_ids import FIREFOX, is_firefox, is_tab_id
from app.persistence.config_manager import ConfigManager
from app.ui.panels import browser_tabs, page_pool as pp
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit

FF_ID = "9THrgpBc.Profile1_tab0"


def ff_tab(id_=FF_ID, url="https://arena.ai/c/9"):
    return FirefoxTab(id=id_, url=url, title="Arena", profile_dir="/profiles/9THrgpBc.Profile1",
                      profile_name="Profile1", tab_index=0)


def chrome_row(id_="t1", ws="ws://x/t1"):
    return SimpleNamespace(id=id_, url="https://arena.ai/c/1", title="T",
                           ws_url=ws, type="page", browser="chrome")


def env_with(tmp_path, pool=True):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge._page_pool = PagePool() if pool else None
    return env


# ── the browser fields (page_status / page_pool) ─────────────────────────────

def test_conn_is_derived_from_the_browser_id_always():
    assert ps.conn_of("firefox") == "uivision"
    assert ps.conn_of("chrome") == "cdp"
    assert ps.conn_of("anything-else") == "cdp"
    assert ps.FIREFOX == FIREFOX == "firefox"


def test_is_firefox_accepts_strings_and_objects():
    assert is_firefox("firefox") and is_firefox(SimpleNamespace(browser="firefox"))
    assert not is_firefox("chrome") and not is_firefox(SimpleNamespace())
    assert ps.is_firefox is is_firefox


def test_page_info_carries_the_profile_and_the_snapshot_carries_conn(tmp_path):
    env = env_with(tmp_path)
    pool = env.bridge._page_pool
    pool.add_page(discovered_page_info(ff_tab()))
    page = pool.get_page(FF_ID)
    assert page.profile == "/profiles/9THrgpBc.Profile1"
    assert page.to_dict()["profile"] == page.profile
    entry = pool.status_snapshot()["pages"][0]
    assert entry["browser"] == "firefox" and entry["conn"] == "uivision"
    assert entry["browser"] == "firefox"


def test_a_chrome_snapshot_entry_still_reads_cdp(tmp_path):
    from app.browser.page_status import PageInfo
    env = env_with(tmp_path)
    env.bridge._page_pool.add_page(PageInfo(tab_id="t1", url="https://arena.ai", title="T"))
    entry = env.bridge._page_pool.status_snapshot()["pages"][0]
    assert entry["conn"] == "cdp" and entry["browser"] == "chrome"


def test_the_stable_id_seam_is_shared():
    assert is_tab_id(FF_ID)
    from app.browser.uivision import discovery
    assert discovery.is_tab_id is is_tab_id


# ── join_discovered_page (the ui seam, D-5) ──────────────────────────────────

def test_join_discovered_page_pools_the_row_and_announces_it(tmp_path):
    env = env_with(tmp_path)
    assert pp.join_discovered_page(env.bridge, ff_tab()) is True
    page = env.bridge._page_pool.get_page(FF_ID)
    assert page is not None and page.browser == "firefox"
    assert page.is_free()                      # steady from the moment it joins
    assert any("🦊 Pool added" in m for m, _lvl in env.recs["arena_log"].calls)
    assert pp.join_discovered_page(env.bridge, ff_tab()) is False, "never twice"


def test_join_discovered_page_needs_a_pool_and_an_id(tmp_path):
    env = env_with(tmp_path, pool=False)
    assert pp.join_discovered_page(env.bridge, ff_tab()) is False
    env.bridge._page_pool = PagePool()
    assert pp.join_discovered_page(env.bridge, SimpleNamespace(id="")) is False


@pytest.mark.asyncio
async def test_rejoin_routes_firefox_to_the_page_join_and_chrome_to_the_socket(tmp_path, monkeypatch):
    env = env_with(tmp_path)
    sockets = []

    async def connect(_bridge, ws):
        sockets.append(ws)
    monkeypatch.setattr(pp, "do_connect_page_pool", connect)
    pool = env.bridge._page_pool
    tabs = {FF_ID: ff_tab(), "t1": chrome_row(), "t2": chrome_row("t2", ws="")}

    assert await pp._rejoin_one(env.bridge, pool, tabs, FF_ID) is True
    assert pool.get_page(FF_ID) is not None and sockets == []
    assert await pp._rejoin_one(env.bridge, pool, tabs, FF_ID) is False, "already pooled"

    assert await pp._rejoin_one(env.bridge, pool, tabs, "t1") is True
    assert sockets == ["ws://x/t1"], "chrome still joins through its socket"
    assert await pp._rejoin_one(env.bridge, pool, tabs, "t2") is False
    assert await pp._rejoin_one(env.bridge, pool, tabs, "missing") is False
    skipped = [m for m, _l in env.recs["arena_log"].calls if "Rejoin skipped" in m]
    assert len(skipped) == 2, "socketless and closed tabs both say why"


@pytest.mark.asyncio
async def test_rejoin_checked_rows_fetches_once_and_wakes_the_bus(tmp_path, monkeypatch):
    env = env_with(tmp_path)
    tabs = {FF_ID: ff_tab(), "t1": chrome_row()}
    monkeypatch.setattr(pp, "_live_tabs", _async_return(tabs))
    assert await pp.rejoin_checked_rows(env.bridge, []) == 0
    joined = await pp.rejoin_checked_rows(env.bridge, [FF_ID, "t1"])
    assert joined == 2
    assert env.bridge._page_pool.get_page(FF_ID) is not None


def _async_return(value):
    async def _inner(_bridge):
        return value
    return _inner


# ── browser_tabs: the merged fetch (D-1) ─────────────────────────────────────

def test_real_discovery_is_off_for_every_test(tmp_path):
    assert browser_tabs.DISCOVERY_ENABLED is False, "conftest's kill switch"


def test_firefox_rows_prefer_the_injected_source(tmp_path):
    env = env_with(tmp_path)
    env.bridge._firefox_rows = lambda: [ff_tab()]
    assert [t.id for t in browser_tabs.firefox_rows(env.bridge)] == [FF_ID]
    env.bridge._firefox_rows = None
    assert browser_tabs.firefox_rows(env.bridge) == [], "flag is off → no real session read"


def test_firefox_rows_discover_when_the_flag_is_on(tmp_path, monkeypatch):
    env = env_with(tmp_path)
    monkeypatch.setattr(browser_tabs, "DISCOVERY_ENABLED", True)
    monkeypatch.setattr("app.browser.uivision.discovery.discover",
                        lambda **kw: [ff_tab()])
    assert [t.id for t in browser_tabs.firefox_rows(env.bridge)] == [FF_ID]


@pytest.mark.asyncio
async def test_reconcile_tabs_merges_both_browsers(tmp_path, monkeypatch):
    env = env_with(tmp_path)
    monkeypatch.setattr(browser_tabs, "live_tab_rows",
                        _async_return_static([chrome_row()]))
    monkeypatch.setattr(browser_tabs, "_firefox_rows",
                        _async_return_static([ff_tab()]))
    rows = await browser_tabs.reconcile_tabs(env.bridge)
    assert len(rows) == 2
    assert env.bridge._chrome_scan_down is False


@pytest.mark.asyncio
async def test_a_dead_chrome_with_live_firefox_still_answers_a_pass(tmp_path, monkeypatch):
    env = env_with(tmp_path)
    env.bridge._scan_failed = "chrome endpoint gone"
    monkeypatch.setattr(browser_tabs, "live_tab_rows", _async_return_static([]))
    monkeypatch.setattr(browser_tabs, "_firefox_rows", _async_return_static([ff_tab()]))
    rows = await browser_tabs.reconcile_tabs(env.bridge)
    assert [r.id for r in rows] == [FF_ID]
    assert env.bridge._chrome_scan_down is True, "the service protects Chrome's rows now"


@pytest.mark.asyncio
async def test_nothing_to_fetch_at_all_is_still_a_wait(tmp_path, monkeypatch):
    from app.services.live.reconcile import ScanUnavailable
    env = env_with(tmp_path)
    env.bridge._scan_failed = "chrome endpoint gone"
    monkeypatch.setattr(browser_tabs, "live_tab_rows", _async_return_static([]))
    monkeypatch.setattr(browser_tabs, "_firefox_rows", _async_return_static([]))
    with pytest.raises(ScanUnavailable):
        await browser_tabs.reconcile_tabs(env.bridge)


def _async_return_static(value):
    async def _inner(_bridge):
        return value
    return _inner


# ── the live_deps wiring (the panel owns the seam) ───────────────────────────

def test_live_deps_wires_join_entry_to_the_pool_panel():
    import inspect
    from app.services.live.reconcile import LiveDeps
    from app.ui.panels import browser_tabs as bt
    deps = LiveDeps(fetch_tabs=lambda: None, join_tab=lambda ws: None,
                    commit=lambda: None, log=lambda *a: None)
    assert deps.join_entry is None, "chrome-only constructions stay valid (D-5)"
    src = inspect.getsource(bt.live_deps)
    assert "join_entry" in src and "join_discovered_page" in src

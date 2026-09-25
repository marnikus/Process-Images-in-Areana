"""Firefox rows through the ONE listing seam (2026-09-25, design D1/D3).

`browser_tabs.reconcile_tabs` = Chrome rows + Firefox rows; the sentinel
`firefox://…` joins through `LiveDeps.join_tab` routing, presence keeps the
page alive, and a Chrome endpoint that did not answer skips the WHOLE pass
(a failed fetch is a wait, not a removal) even when Firefox answered.

RED at base: no firefox rows appear and the sentinel never joins.
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.uivision import pool_tabs as pt
from app.core.models import UrlRow
from app.services.live import reconcile as rc
from app.ui.panels import browser_tabs
from app.ui.panels.page_pool import leave_pool
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit

FF_TAB = "9THrgpBc.Profile1_tab1"


def chrome_tab(id_, url="https://other.example/x"):
    return SimpleNamespace(id=id_, title="T", url=url,
                           ws_url=f"ws://127.0.0.1:9222/devtools/page/{id_}", type="page")


class Deps:
    """LiveDeps wired to the REAL seam: reconcile_tabs (its fetch) + the join router."""

    def __init__(self, bridge):
        self.commits, self.lines = 0, []
        self.bridge = bridge

    async def fetch_tabs(self):
        return await browser_tabs.reconcile_tabs(self.bridge)

    async def join_tab(self, ws):
        await browser_tabs.route_join_tab(self.bridge, ws)

    def leave_tab(self, tab_id: str) -> bool:
        left = leave_pool(self.bridge, tab_id)
        self.bridge._emit_pool_status()
        return left

    def commit(self):
        self.commits += 1
        self.bridge._save_arena()

    def log(self, msg, level="info"):
        self.lines.append(msg)

    def as_deps(self):
        return rc.LiveDeps(fetch_tabs=self.fetch_tabs, join_tab=self.join_tab,
                           leave_tab=self.leave_tab, commit=self.commit, log=self.log)


def env_with(tmp_path, urls=None):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge.state.urls = list(urls or [])
    env.bridge._page_pool = PagePool(logger=lambda m, l="info": None)
    env.deps = Deps(env.bridge)
    return env


def fake_firefox(tmp_path, monkeypatch, url="https://arena.ai/c/7", title="FF", rows=None):
    d = tmp_path / "9THrgpBc.Profile1"
    d.mkdir(exist_ok=True)
    body = rows if rows is not None else [{"url": url, "title": title}]
    monkeypatch.setattr(pt.tabs, "profile_sessions",
                        lambda profiles=None: [{"name": "P1", "dir": str(d), "rows": body,
                                                "windows": [], "source": "s", "stamp": 1.0}])
    monkeypatch.setattr(pt.profiles, "open_sessions", lambda sessions, in_use=None: sessions)


def chrome_answers(monkeypatch, tabs=None):
    async def rows(_bridge):
        return list(tabs if tabs is not None else [chrome_tab("c1")])
    monkeypatch.setattr(browser_tabs, "live_tab_rows", rows)


@pytest.mark.asyncio
async def test_firefox_tab_enters_rows_and_pool_via_sentinel(tmp_path, monkeypatch):
    fake_firefox(tmp_path, monkeypatch)
    chrome_answers(monkeypatch)
    env = env_with(tmp_path)
    report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert report.added == 1
    row = env.bridge.state.urls[0]
    assert row.tab_id == FF_TAB
    page = env.bridge._page_pool.get_page(FF_TAB)
    assert page is not None and page.browser == "firefox" and page.is_free()
    assert env.deps.commits == 1
    assert any("🔺 URL added https://arena.ai/c/7" in m for m in env.deps.lines)


@pytest.mark.asyncio
async def test_cdp_failure_skips_the_pass_before_the_firefox_merge(tmp_path, monkeypatch):
    from app.services.live.reconcile import ScanUnavailable
    fake_firefox(tmp_path, monkeypatch)
    linked = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="c1")

    async def dead(_bridge):
        raise ScanUnavailable("endpoint down")

    monkeypatch.setattr(browser_tabs, "live_tab_rows", dead)
    env = env_with(tmp_path, urls=[linked])
    for _ in range(3):
        report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
        assert report.removed == 0
        assert env.bridge.state.urls == [linked]
        assert env.bridge._page_pool.get_page("c1") is None
    assert env.bridge.state.urls[0].tab_id == "c1"  # untouched, Firefox never merged in


@pytest.mark.asyncio
async def test_closing_the_firefox_tab_removes_row_and_pool_page(tmp_path, monkeypatch):
    fake_firefox(tmp_path, monkeypatch)
    chrome_answers(monkeypatch)
    env = env_with(tmp_path)
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert env.bridge._page_pool.get_page(FF_TAB) is not None
    monkeypatch.setattr(pt.tabs, "profile_sessions", lambda profiles=None: [])
    for _ in range(4):   # miss hysteresis (threshold 2) + the orphan-exit pass
        await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert env.bridge.state.urls == []
    assert env.bridge._page_pool.get_page(FF_TAB) is None
    assert any(m.startswith("🔻 URL removed") for m in env.deps.lines)


@pytest.mark.asyncio
async def test_unchecked_firefox_row_leaves_the_pool(tmp_path, monkeypatch):
    fake_firefox(tmp_path, monkeypatch)
    chrome_answers(monkeypatch)
    env = env_with(tmp_path)
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    env.bridge.state.urls[0].enabled = False
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert env.bridge._page_pool.get_page(FF_TAB) is None
    assert any("🚪" in m for m in env.deps.lines)


@pytest.mark.asyncio
async def test_rejoin_restores_an_unchecked_then_checked_row(tmp_path, monkeypatch):
    fake_firefox(tmp_path, monkeypatch)
    chrome_answers(monkeypatch)
    env = env_with(tmp_path)
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    env.bridge.state.urls[0].enabled = False
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert env.bridge._page_pool.get_page(FF_TAB) is None
    env.bridge.state.urls[0].enabled = True
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    page = env.bridge._page_pool.get_page(FF_TAB)
    assert page is not None and page.is_free()


def test_firefox_rows_survive_a_broken_config_read(tmp_path, monkeypatch):
    """A config that cannot be read falls back to EVERY profile (D1) — never a crash."""
    fake_firefox(tmp_path, monkeypatch)
    from app.browser.uivision import config as uv_cfg
    monkeypatch.setattr(uv_cfg, "load_config",
                        lambda bridge: (_ for _ in ()).throw(RuntimeError("session.json corrupt")))
    rows = browser_tabs._firefox_rows(object())
    assert [r.id for r in rows] == [FF_TAB]


def test_join_skips_honestly_when_the_tab_vanished(tmp_path, monkeypatch):
    """find_tab comes back empty → warn + no pool add; the next pass owns removal."""
    env = env_with(tmp_path)
    monkeypatch.setattr(pt.tabs, "profile_sessions", lambda profiles=None: [])
    logs = []
    env.bridge._log = lambda msg, level="info": logs.append(msg)
    browser_tabs._join_firefox(env.bridge, f"firefox://{FF_TAB}")
    assert env.bridge._page_pool.get_page(FF_TAB) is None
    assert any("tab no longer open" in m for m in logs)


@pytest.mark.asyncio
async def test_rejoin_one_skips_a_row_that_is_pooled_already(tmp_path):
    from types import SimpleNamespace as NS
    from app.ui.panels import page_pool as pp
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id=FF_TAB, url="https://arena.ai/c/7", title="A",
                        profile="P1", profile_dir="/x/P1", ws_url=f"firefox://{FF_TAB}")
    pool.add_page(pt.page_for(tab))
    joined = await pp._rejoin_one(NS(_log=lambda *a, **k: None), pool,
                                  {FF_TAB: f"firefox://{FF_TAB}"}, FF_TAB)
    assert joined is False      # already pooled — nothing to restore

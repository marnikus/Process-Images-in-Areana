"""S6 · `live/reconcile` — the Python-owned URL reconciler (D-4 / D-10 / I-50).

Rows follow Chrome in every run state at a user-set cadence (read every
pass), an empty or failed fetch never removes, a new matching tab is added +
claimed + joined through `LiveDeps.join_tab` (S1's repaired path), every row
change commits through `commit_urls` with no undo entry, and the loop wakes
the live bus with `urls`. Real `Bridge` from the golden harness, fakes only
behind the `LiveDeps` seam. The JS 15 s timer is gone (source lock).

RED at base: `ModuleNotFoundError: app.services.live.reconcile`.
"""

import asyncio
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.models import UrlRow
from app.services.live import reconcile as rc
from app.services.live.bus import live_bus
from app.ui.panels import browser_tabs
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit
JS = Path(__file__).resolve().parents[1] / "app" / "ui" / "web" / "js"


def tab(id_, url="https://arena.ai/c/1"):
    return SimpleNamespace(id=id_, title="T", url=url, ws_url=f"ws://127.0.0.1:9222/devtools/page/{id_}", type="page")


class Deps:
    """A `LiveDeps` with recorders: tabs are scripted per call, joins/commits counted."""

    def __init__(self, bridge, *fetches):
        self.fetches, self.joined, self.commits, self.lines = list(fetches), [], 0, []
        self.bridge = bridge

    async def fetch_tabs(self):
        item = self.fetches.pop(0) if len(self.fetches) > 1 else self.fetches[0]
        if isinstance(item, Exception):
            raise item
        return item

    async def join_tab(self, ws):
        self.joined.append(ws)

    def commit(self):
        self.commits += 1
        self.bridge._save_arena()

    def log(self, msg, level="info"):
        self.lines.append(msg)

    def as_deps(self):
        return rc.LiveDeps(fetch_tabs=self.fetch_tabs, join_tab=self.join_tab, commit=self.commit, log=self.log)


def env_with(tmp_path, *fetches, urls=None):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge.state.urls = list(urls or [])
    env.bridge._page_pool = None
    env.deps = Deps(env.bridge, *fetches)
    return env


@pytest.mark.asyncio
async def test_a_new_tab_is_added_claimed_and_joined(tmp_path):
    typed = UrlRow.create("https://arena.ai/c/2", enabled=True)  # user-typed, unlinked
    env = env_with(tmp_path, [tab("t1"), tab("t2", "https://arena.ai/c/2"), tab("t3", "https://other.example/x")], urls=[typed])
    report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert (report.added, report.linked, report.removed) == (1, 1, 0)
    assert typed.tab_id == "t2"
    assert env.deps.joined == [tab("t1").ws_url, tab("t2").ws_url]  # through the seam, not do_connect_page_pool
    assert env.deps.commits == 1
    assert live_bus(env.bridge).reasons() == ["urls"]
    assert any(m.startswith("🔺 URL added https://arena.ai/c/1") for m in env.deps.lines)
    assert any(m.startswith("🔗 URL linked") and "t2" in m for m in env.deps.lines)


@pytest.mark.asyncio
async def test_an_empty_fetch_never_removes_rows(tmp_path):
    linked = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = env_with(tmp_path, [], urls=[linked])
    for _ in range(3):
        report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
        assert report.removed == 0 and env.bridge.state.urls == [linked]
    env.deps.fetches = [RuntimeError("chrome down")]
    report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert report.removed == 0 and env.bridge.state.urls == [linked] and report.error
    assert env.deps.commits == 0 and live_bus(env.bridge).reasons() == []


@pytest.mark.asyncio
async def test_a_closed_tab_is_removed_with_a_reason_and_wakes_the_loop(tmp_path):
    linked = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    keep = UrlRow.create("https://arena.ai/c/2", enabled=True, tab_id="t2")
    env = env_with(tmp_path, [tab("t2", "https://arena.ai/c/2")], urls=[linked, keep])
    first = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert first.removed == 0 and len(env.bridge.state.urls) == 2  # hysteresis: one miss is not a removal
    second = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert second.removed == 1 and env.bridge.state.urls == [keep]
    assert any(m.startswith("🔻 URL removed https://arena.ai/c/1") and "tab closed" in m for m in env.deps.lines)
    assert "urls" in live_bus(env.bridge).reasons()


@pytest.mark.asyncio
async def test_a_row_under_a_live_job_is_deferred(tmp_path):
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo
    from app.services.cooldown_service import set_tab_image
    busy = UrlRow.create("https://example.com/x", enabled=True, tab_id="t1")  # pattern mismatch, but working
    env = env_with(tmp_path, [tab("t1", "https://example.com/x")], urls=[busy])
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url=tab("t1").ws_url, title="T", url="https://example.com/x", is_connected=True))
    set_tab_image(pool, "t1", "a.png")
    env.bridge._page_pool = pool
    report = await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    assert (report.removed, report.deferred) == (0, 1) and env.bridge.state.urls == [busy]
    assert any(m.startswith("⏸ URL removal deferred") for m in env.deps.lines)


@pytest.mark.parametrize("run_state", ["idle", "running", "paused"])
@pytest.mark.asyncio
async def test_reconcile_runs_in_every_run_state(tmp_path, run_state):
    gone = UrlRow.create("https://arena.ai/c/9", enabled=True, tab_id="t9")
    env = env_with(tmp_path, [tab("t1")], urls=[gone])
    env.bridge._run_state = run_state
    reports = [await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto") for _ in range(2)]
    assert (reports[0].added, reports[1].removed) == (1, 1)  # identical in every state (no idle-only prune)


@pytest.mark.asyncio
async def test_the_interval_is_read_every_pass(tmp_path, monkeypatch):
    env = env_with(tmp_path, [tab("t1")])
    env.bridge.config.set_state(url_reconcile_interval_ms=5000)
    slept = []

    async def fake_wait(timeout_s):
        slept.append(timeout_s)
        if len(slept) == 1:
            env.bridge.config.set_state(url_reconcile_interval_ms=700)
        if len(slept) == 2:
            raise asyncio.CancelledError
        return ""
    monkeypatch.setattr(live_bus(env.bridge), "wait", fake_wait)
    with pytest.raises(asyncio.CancelledError):
        await rc.reconcile_loop(env.bridge, env.deps.as_deps())
    assert slept == [5.0, 0.7]  # no restart needed
    assert rc.last_pass_at(env.bridge) > 0 and rc.pass_count(env.bridge) == 2


@pytest.mark.asyncio
async def test_commit_goes_through_the_single_row_funnel_without_undo(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge.state.urls = []
    env.bridge._page_pool = None
    history_before = env.bridge.undo_service.history()
    deps = browser_tabs.live_deps(env.bridge)
    assert deps.commit.func.__name__ == "commit_urls_system"  # commit_urls minus the undo entry
    joined = []

    async def fake_join(ws):
        joined.append(ws)
    deps = rc.LiveDeps(fetch_tabs=lambda: _tabs([tab("t1")]), join_tab=fake_join, commit=deps.commit, log=deps.log)
    report = await rc.reconcile_once(env.bridge, deps, "manual")
    assert report.added == 1 and joined == [tab("t1").ws_url]
    assert env.bridge.undo_service.history() == history_before  # system change: no undo entry (I-37)
    assert env.recs["arena_state_updated"].calls  # but the table was pushed


async def _tabs(items):
    return items


def test_the_manual_slot_triggers_an_immediate_pass(tmp_path, monkeypatch):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge._page_pool = object()
    scheduled = []
    monkeypatch.setattr(browser_tabs, "schedule_coro", lambda b, coro: scheduled.append(coro) or coro)
    assert env.bridge.auto_connect_scan("manual") == "pending"
    assert len(scheduled) == 1 and scheduled[0].cr_code.co_name == "reconcile_once"
    scheduled[0].close()


def test_start_reconciler_is_idempotent(tmp_path, monkeypatch):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    scheduled = []
    monkeypatch.setattr(rc, "schedule_coro", lambda b, coro: scheduled.append(coro) or SimpleNamespace(done=lambda: False))
    assert browser_tabs.start_url_reconciler(env.bridge) is True
    assert browser_tabs.start_url_reconciler(env.bridge) is False  # second start: no second loop
    assert len(scheduled) == 1 and scheduled[0].cr_code.co_name == "reconcile_loop"
    scheduled[0].close()


def test_services_never_import_ui_or_browser():
    for mod in ("reconcile", "url_policy", "row_sync", "sources"):   # I-64 split + multi-source helpers
        src = (Path(rc.__file__).parent / f"{mod}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import) app\.(ui|browser)\b", src, re.M), mod


def test_the_js_timer_is_gone():
    src = (JS / "panels" / "cdp.js").read_text(encoding="utf-8")
    assert "autoConnectScan(), 15000" not in src
    assert src.count("setInterval") == 1  # the 500 ms ensurePrimary tick stays
    assert "delegation" in inspect.getdoc(browser_tabs.auto_scan_pass).lower()  # the body moved out of the panel

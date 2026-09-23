"""Reparse fresh sweep + the checkbox owns pool membership (2026-09-21, D-2…D-5).

Manual Reparse clears every row whose tab has no live job, remembers each
checkbox, then the same pass rebuilds the list from the fetched tabs
(fetch-first: a failed fetch never removes, I-50). `url_policy.pool_exits`
is the ONE membership decision (checkbox off OR no row at all): such a tab leaves the pool
(instantly on toggle through `leave_pool`, every pass through the
reconciler's `LiveDeps.leave_tab`), a busy tab defers, and
`plan_auto_connect` never auto-rejoins a tab whose row is unchecked.

RED at base: `pool_exits` missing; a manual pass keeps stale rows.
"""

import json

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services import auto_connect as ac
from app.services.cooldown_service import set_tab_image
from app.services.live import reconcile as rc
from app.services.live import url_policy as up
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit


def tab(id_, url="https://arena.ai/c/1"):
    from types import SimpleNamespace
    return SimpleNamespace(id=id_, title="T", url=url,
                           ws_url=f"ws://127.0.0.1:9222/devtools/page/{id_}", type="page")


class Deps(rc.LiveDeps):
    """Recorders behind the seam; `leave_tab` really leaves the pool (the one ui mechanic)."""

    def __init__(self, bridge, *fetches):
        super().__init__(fetch_tabs=self._fetch, join_tab=self._join, commit=self._commit, log=self._log)
        self.bridge = bridge
        self.leave_tab = self._leave  # the dataclass field default would shadow a same-named method
        self.fetches, self.joined, self.left, self.lines = list(fetches), [], [], []

    async def _fetch(self):
        item = self.fetches.pop(0) if len(self.fetches) > 1 else self.fetches[0]
        if isinstance(item, Exception):
            raise item
        return item

    async def _join(self, ws):
        self.joined.append(ws)

    def _commit(self):
        self.bridge._save_arena()

    def _log(self, msg, level="info"):
        self.lines.append(msg)

    def _leave(self, tab_id):
        from app.ui.panels.page_pool import leave_pool
        left = leave_pool(self.bridge, tab_id)  # badge-clear skipped (no client), page removed
        self.left.append(tab_id)
        return left


def mkenv(tmp_path, *fetches, urls=None, pool=None):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool)
    env.bridge.state.urls = list(urls or [])
    env.deps = Deps(env.bridge, *fetches)
    return env


# ── D-2: manual Reparse sweeps, then rebuilds ──


@pytest.mark.asyncio
async def test_manual_reparse_rebuilds_the_list_from_open_tabs(tmp_path):
    old = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = mkenv(tmp_path, [tab("t1"), tab("t2", "https://arena.ai/c/2")], urls=[old])
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    urls = env.bridge.state.urls
    assert [u.url for u in urls] == ["https://arena.ai/c/1", "https://arena.ai/c/2"]
    assert old.id not in {u.id for u in urls}  # fresh rows, not patched old ones
    assert report.swept == 1 and report.added == 2
    assert any(m.startswith("🧹 Reparse: cleared 1 URL row(s)") for m in env.deps.lines)


@pytest.mark.asyncio
async def test_the_sweep_restores_the_checkbox_the_user_left(tmp_path):
    unchecked = UrlRow.create("https://arena.ai/c/1", enabled=False, tab_id="t1")
    env = mkenv(tmp_path, [tab("t1")], urls=[unchecked])
    await rc.reconcile_once(env.bridge, env.deps, "manual")
    (row,) = env.bridge.state.urls
    assert row.url == "https://arena.ai/c/1" and row.enabled is False  # memory restored it
    assert row.id != unchecked.id


@pytest.mark.asyncio
async def test_a_busy_row_keeps_its_identity_and_assignment(tmp_path):
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url=tab("t1").ws_url, title="T", url="https://arena.ai/c/1"))
    set_tab_image(pool, "t1", "a.png")  # live job on the tab
    busy = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    busy.receiver = True
    env = mkenv(tmp_path, [tab("t1")], urls=[busy], pool=pool)
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert env.bridge.state.urls == [busy] and report.swept == 0
    assert any("kept" in m for m in env.deps.lines)  # the sweep says why it kept the row


@pytest.mark.asyncio
async def test_a_failed_fetch_never_sweeps(tmp_path):
    linked = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = mkenv(tmp_path, RuntimeError("chrome down"), urls=[linked])
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert env.bridge.state.urls == [linked] and report.error and report.swept == 0


@pytest.mark.asyncio
async def test_the_sweep_unassigns_images_of_cleared_rows_and_says_so(tmp_path):
    from tests.characterization.harness import make_images
    row = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = mkenv(tmp_path, [tab("t1")], urls=[row])
    env.bridge.state.images = make_images(tmp_path, 1)
    env.bridge.state.images[0].assigned_url_id = row.id
    await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert env.bridge.state.images[0].assigned_url_id is None
    (fresh,) = env.bridge.state.urls
    assert fresh.id != row.id  # the image follows the fresh row, not the dead one
    assert any("unassigned" in m for m in env.deps.lines)


@pytest.mark.asyncio
async def test_an_auto_pass_never_sweeps(tmp_path):
    linked = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env = mkenv(tmp_path, [tab("t1")], urls=[linked])
    report = await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert report.swept == 0 and report.removed == 0 and report.added == 0
    assert not any(m.startswith("🧹") for m in env.deps.lines)


# ── D-3: `pool_exits` — the one checkbox→pool decision ──


def pool_with(*tab_ids):
    pool = PagePool(logger=lambda m, l="info": None)
    for tid in tab_ids:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", title="T", url="https://arena.ai"))
    return pool


def test_pool_exits_kicks_unchecked_pooled_rows_only():
    pool = pool_with("t1", "t2")
    out = UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1")
    keep = UrlRow.create("https://arena.ai/2", enabled=True, tab_id="t2")
    unlinked = UrlRow.create("https://arena.ai/3", enabled=False, tab_id="")
    leaves, deferred = up.pool_exits([out, keep, unlinked], pool)
    assert [(e.tab_id, e.reason) for e in leaves] == [("t1", "unchecked")] and deferred == []
    assert leaves[0].row is out  # the exit names the row that owns the tab


def test_pool_exits_defers_a_row_under_a_live_job():
    pool = pool_with("t1")
    set_tab_image(pool, "t1", "a.png")
    busy = UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1")
    leaves, deferred = up.pool_exits([busy], pool)
    assert leaves == [] and [(e.tab_id, e.reason) for e in deferred] == [("t1", "unchecked")]


def test_pool_exits_without_a_pool_is_empty():
    row = UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1")
    assert up.pool_exits([row], None) == ([], [])


# ── D-4: the reconciler enforces membership through the seam ──


@pytest.mark.asyncio
async def test_the_pass_puts_unchecked_tabs_out_of_the_pool(tmp_path):
    pool = pool_with("t1", "t2")
    off = UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1")
    on = UrlRow.create("https://arena.ai/2", enabled=True, tab_id="t2")
    env = mkenv(tmp_path, [tab("t1", "https://arena.ai/1"), tab("t2", "https://arena.ai/2")],
              urls=[off, on], pool=pool)
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert env.deps.left == ["t1"] and pool.get_page("t1") is None and pool.get_page("t2") is not None
    assert any("left the worker pool" in m for m in env.deps.lines)


@pytest.mark.asyncio
async def test_a_busy_unchecked_tab_defers_its_exit_once(tmp_path):
    pool = pool_with("t1")
    set_tab_image(pool, "t1", "a.png")
    off = UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1")
    env = mkenv(tmp_path, [tab("t1", "https://arena.ai/1")], urls=[off], pool=pool)
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert env.deps.left == [] and pool.get_page("t1") is not None
    assert sum("Pool exit deferred" in m for m in env.deps.lines) == 1  # logged once per streak


# ── D-5: no auto-rejoin while unchecked ──


def test_plan_does_not_rejoin_a_tab_whose_row_is_unchecked():
    rows = [{"id": "r1", "url": "https://arena.ai/1", "tab_id": "t1", "enabled": False}]
    plan = ac.plan_auto_connect([tab("t1", "https://arena.ai/1")], "arena.ai", rows, set())
    assert plan.connect == [] and plan.claim == [] and plan.add == []


def test_plan_rejoins_when_the_row_is_checked_or_legacy():
    for rows in ([{"id": "r1", "url": "https://arena.ai/1", "tab_id": "t1", "enabled": True}],
                 [{"id": "r1", "url": "https://arena.ai/1", "tab_id": "t1"}]):  # legacy dict, no key
        plan = ac.plan_auto_connect([tab("t1", "https://arena.ai/1")], "arena.ai", rows, set())
        assert len(plan.connect) == 1


# ── D-4: the toggle slot — instant exit on the real Bridge ──


def test_live_deps_wires_the_leave_mechanic(tmp_path):
    from app.ui.panels.browser_tabs import live_deps
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool_with("t1"))
    emitted = []
    env.bridge._emit_pool_status = lambda: emitted.append(1)
    deps = live_deps(env.bridge)
    assert deps.leave_tab("t1") is True and env.bridge._page_pool.get_page("t1") is None
    assert deps.leave_tab("t1") is False and emitted  # gone is gone; the push still rode out


def test_unchecking_a_row_removes_its_tab_from_the_pool(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool_with("t1"))
    row = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env.bridge.state.urls = [row]
    res = json.loads(env.bridge.toggle_url(row.id))
    assert res == {"ok": True, "enabled": False}
    assert env.bridge._page_pool.get_page("t1") is None
    assert any("left the worker pool" in m for m, _l in env.recs["arena_log"].calls)


def test_unchecking_a_busy_row_defers_and_keeps_the_tab(tmp_path):
    pool = pool_with("t1")
    set_tab_image(pool, "t1", "a.png")
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool)
    row = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    env.bridge.state.urls = [row]
    assert json.loads(env.bridge.toggle_url(row.id))["ok"] is True
    assert pool.get_page("t1") is not None
    assert any("Pool exit deferred" in m for m, _l in env.recs["arena_log"].calls)


def test_checking_a_row_removes_nothing(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool_with("t1"))
    row = UrlRow.create("https://arena.ai/c/1", enabled=False, tab_id="t1")
    env.bridge.state.urls = [row]
    assert json.loads(env.bridge.toggle_url(row.id))["enabled"] is True
    assert env.bridge._page_pool.get_page("t1") is not None  # rejoin is the reconciler's job (next pass)


# ── I-56: the join half of the checkbox gate acts on the toggle ──


def test_checking_a_row_schedules_the_rejoin_now(tmp_path, monkeypatch):
    """RED at base: the toggle only removed the tab and left the rejoin to the next pass."""
    from app.ui.panels import url_queue
    scheduled = []
    monkeypatch.setattr(url_queue, "schedule_coro", lambda bridge, coro: scheduled.append(coro))
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=PagePool())
    row = UrlRow.create("https://arena.ai/c/1", enabled=False, tab_id="t1")
    env.bridge.state.urls = [row]
    assert json.loads(env.bridge.toggle_url(row.id))["enabled"] is True
    assert len(scheduled) == 1 and scheduled[0].cr_code.co_name == "rejoin_checked_rows"
    assert scheduled[0].cr_frame.f_locals["tab_ids"] == ["t1"]
    scheduled[0].close()
    assert any("Checked URLs not pooled — rejoining 1 tab(s) now" in m for m, _l in env.recs["arena_log"].calls)


def test_entering_the_pool_skips_a_pooled_tab_and_an_unlinked_row(tmp_path, monkeypatch):
    from app.ui.panels import url_queue
    scheduled = []
    monkeypatch.setattr(url_queue, "schedule_coro", lambda bridge, coro: scheduled.append(coro))
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool_with("t1"))
    pooled = UrlRow.create("https://arena.ai/1", enabled=True, tab_id="t1")
    unlinked = UrlRow.create("https://arena.ai/2", enabled=True, tab_id="")
    unchecked = UrlRow.create("https://arena.ai/3", enabled=False, tab_id="t9")
    env.bridge.state.urls = [pooled, unlinked, unchecked]
    assert url_queue.enter_pool_for_checked(env.bridge) == []
    assert scheduled == []  # nothing to do: the worker is already pooled / never linked / unchecked


@pytest.mark.asyncio
async def test_the_instant_rejoin_puts_the_tab_back(tmp_path, monkeypatch):
    from app.services.live.bus import live_bus
    from app.ui.panels import page_pool as pp

    class FakeClient:
        async def evaluate(self, js):
            return "ok"

    async def fake_connect(bridge, ws_url):
        return FakeClient()

    async def fake_tabs():
        return [tab("t1")]

    async def fake_info(bridge, tab_id, ws_url):
        return "T", "https://arena.ai/c/1"

    monkeypatch.setattr(pp, "connect_pool_client", fake_connect)
    monkeypatch.setattr(pp, "resolve_tab_info", fake_info)
    monkeypatch.setattr(pp, "restore_page_state", lambda bridge, tab_id: None)
    monkeypatch.setattr("app.browser.cdp_arena.CDPArenaController", lambda client, log_callback: object())
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=PagePool())
    monkeypatch.setattr(env.cdp, "fetch_tabs", fake_tabs)
    assert await pp.rejoin_checked_rows(env.bridge, ["t1"]) == 1
    page = env.bridge._page_pool.get_page("t1")
    assert page is not None and page.worker_no == 1 and page.is_connected
    assert live_bus(env.bridge).reasons() == ["urls"]  # a live run picks the worker up
    # D-7: the join line names the tab by its readable id, not the raw hex
    assert any(f"Pool added {page.alias}" in m for m, _l in env.recs["arena_log"].calls)


@pytest.mark.asyncio
async def test_the_instant_rejoin_says_when_the_tab_is_gone(tmp_path, monkeypatch):
    from app.ui.panels import page_pool as pp

    async def no_tabs():
        return []

    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=PagePool())
    monkeypatch.setattr(env.cdp, "fetch_tabs", no_tabs)
    assert await pp.rejoin_checked_rows(env.bridge, ["dead01"]) == 0
    assert not any("Pool added dead01" in m for m, _l in env.recs["arena_log"].calls)
    assert any("Rejoin skipped" in m for m, _l in env.recs["arena_log"].calls)

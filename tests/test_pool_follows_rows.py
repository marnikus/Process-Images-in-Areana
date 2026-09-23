"""The pool never holds a worker no URL row owns (2026-09-21, I-58).

User report: "i have 2 url only but the pool have 4 worker … should be same as
url or max as url never more". Reproduced with the real objects: the reconciler
*sees* the extra pages (its own summary says `2 stale`) and keeps them, because
`url_policy.pool_exits` only looked at unchecked rows — a row removed by the
removal table (tab closed / invalid / pattern mismatch / duplicate) or by the ✕
button left its pooled page behind forever, and those pages are the ones the
primary auto-connect latches onto (the `Connect failed … HTTP 500` storm in the
log).

RED at base: `PoolExit` missing and the pass keeps every page.
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services.cooldown_service import set_tab_image
from app.services.live import reconcile as rc
from app.services.live import url_policy as up
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit

A, B, C, D = "a" * 32, "b" * 32, "c" * 32, "d" * 32


def tab(id_, url="https://arena.ai/image/direct?model_a=max"):
    return SimpleNamespace(id=id_, title="T", url=url,
                           ws_url=f"ws://127.0.0.1:9223/devtools/page/{id_}", type="page")


class Deps(rc.LiveDeps):
    """The reconciler seam, plus a `leave_tab` that really leaves the pool."""

    def __init__(self, bridge, tabs):
        super().__init__(fetch_tabs=self._fetch, join_tab=self._join, commit=self._commit, log=self._log)
        self.bridge, self.tabs, self.lines, self.left = bridge, tabs, [], []

    async def _fetch(self):
        return self.tabs

    async def _join(self, ws):
        self.lines.append(("joined", ws))

    def _commit(self):
        self.bridge._save_arena()

    def _log(self, msg, level="info"):
        self.lines.append((msg, level))

    def _leave(self, tab_id):
        from app.ui.panels.page_pool import leave_pool
        left = leave_pool(self.bridge, tab_id)
        if left:
            self.left.append(tab_id)
        return left


def pool_with(*tab_ids):
    pool = PagePool(logger=lambda m, l="info": None)
    for tid in tab_ids:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", title="T",
                               url="https://arena.ai/image/direct?model_a=max"))
    return pool


def mkenv(tmp_path, pool, tabs, urls):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool)
    env.bridge.state.urls = list(urls)
    env.deps = Deps(env.bridge, tabs)
    env.deps.leave_tab = env.deps._leave
    return env


def texts(deps):
    return [m for m, _l in deps.lines]


# ── the rule ──


def test_pool_exits_reports_reasons_for_both_halves():
    pool = pool_with(A, B)
    unchecked = UrlRow.create("https://arena.ai/1", enabled=False, tab_id=A)
    checked = UrlRow.create("https://arena.ai/2", enabled=True, tab_id="")
    leaves, deferred = up.pool_exits([unchecked, checked], pool)
    assert [(e.tab_id, e.reason) for e in leaves] == [(A, "unchecked"), (B, "orphan")]
    assert leaves[0].row is unchecked and leaves[1].row is None
    assert deferred == []
    assert "tab left the worker pool" in up.exit_line(leaves[0]) and unchecked.url in up.exit_line(leaves[0])
    assert "no URL row owns it" in up.exit_line(leaves[1]) and B[:12] in up.exit_line(leaves[1])


def test_a_checked_row_keeps_its_worker():
    pool = pool_with(A)
    row = UrlRow.create("https://arena.ai/1", enabled=True, tab_id=A)
    assert up.pool_exits([row], pool) == ([], [])


def test_pool_exits_without_a_pool_is_empty():
    row = UrlRow.create("https://arena.ai/1", enabled=False, tab_id=A)
    assert up.pool_exits([row], None) == ([], [])


# ── the pass enforcer ──


@pytest.mark.asyncio
async def test_a_pooled_worker_with_no_row_leaves_the_pool(tmp_path):
    row = UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=A)
    env = mkenv(tmp_path, pool_with(A, B, C), [tab(A)], [row])
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert sorted(env.bridge._page_pool._pages) == [A]
    assert env.deps.left == [B, C]
    assert any("no URL row owns it" in m for m in texts(env.deps))


@pytest.mark.asyncio
async def test_the_pool_never_holds_more_workers_than_rows(tmp_path):
    """The reported state: 4 pooled workers, 2 URL rows, 2 of the pages ownerless."""
    pool = pool_with(A, B, C, D)
    rows = [UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=A),
            UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=B)]
    env = mkenv(tmp_path, pool, [tab(A), tab(B)], rows)
    # C and D are the leftovers: their rows were removed by the removal table
    env.deps.leave_tab = env.deps._leave
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert len(pool._pages) == len(env.bridge.state.urls) == 2
    snap = pool.status_snapshot()
    assert snap["total"] == 2 and snap["steady"] == 2
    assert sorted(env.deps.left) == [C, D]


@pytest.mark.asyncio
async def test_a_stale_page_with_a_row_stays(tmp_path):
    """Liveness is not membership (D-3): the 2-miss window still belongs to the row."""
    row = UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=B)
    env = mkenv(tmp_path, pool_with(A, B), [tab(A)], [row])
    report = await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert B in env.bridge._page_pool._pages and env.deps.left == [] and report.stale == 1


@pytest.mark.asyncio
async def test_an_orphan_under_a_live_job_defers_once(tmp_path):
    """D's Chrome target is gone (so no row comes back) but its job is still running."""
    pool = pool_with(A, D)
    set_tab_image(pool, D, "a.png")  # a job is running on the row-less page
    row = UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=A)
    env = mkenv(tmp_path, pool, [tab(A)], [row])
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert D in pool._pages and env.deps.left == []
    assert sum("Pool exit deferred" in m for m in texts(env.deps)) == 1  # once per streak
    set_tab_image(pool, D, None)  # the job ended
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert env.deps.left == [D] and list(pool._pages) == [A]


@pytest.mark.asyncio
async def test_a_manual_join_with_no_row_left_the_worker_pool(tmp_path):
    """D-5: a tab the URL list does not own cannot stay a worker (even when joined by hand)."""
    row = UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=A)
    env = mkenv(tmp_path, pool_with(A, D), [tab(A), tab(D, "https://other.example/page")], [row])
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert sorted(env.bridge._page_pool._pages) == [A]


# ── the UI enforcer (the ONE row write path) ──


def test_deleting_a_row_takes_its_worker_out_at_once(tmp_path):
    """The ✕ on a URL row is a membership edit: its worker leaves in the same commit."""
    pool = pool_with(A, B)
    gone = UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=A)
    kept = UrlRow.create("https://arena.ai/image/direct?model_b=max", enabled=True, tab_id=B)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool)
    env.bridge.state.urls = [gone, kept]
    env.bridge._emit_pool_status = lambda: None
    assert "ok" in env.bridge.remove_url(gone.id)
    assert pool.get_page(A) is None and pool.get_page(B) is not None  # only the orphan left
    assert any("no URL row owns it" in m for m, _l in env.recs["arena_log"].calls)


def test_clearing_the_last_row_empties_the_pool(tmp_path):
    """The user's contract, at its limit: no rows → no workers."""
    pool = pool_with(A)
    row = UrlRow.create("https://arena.ai/image/direct?model_a=max", enabled=True, tab_id=A)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool)
    env.bridge.state.urls = [row]
    env.bridge._emit_pool_status = lambda: None
    assert "ok" in env.bridge.remove_url(row.id)
    assert env.bridge.state.urls == [] and pool._pages == {}

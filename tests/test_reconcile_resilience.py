"""One bad pass must never cost the URL list (2026-09-21, D-1/D-2).

User report: Reparse empties the URL list and the rows never come back; a
re-checked tab never returns to the worker pool. Reproduced end to end the
backend is correct on the happy path (see the design doc), so the reports
describe a *failure* mode: one raise inside the pool phase used to skip
`_commit` (the rebuilt rows never reached the UI or the jar, and the next
unrelated save published the swept list), and one raise anywhere used to end
`reconcile_loop` for the rest of the session (no auto pass rebuilt rows, no
auto pass rejoined a re-checked tab).

RED at base: the join error escapes `reconcile_once` (nothing is committed),
and `reconcile_loop` dies on its first failing pass.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.models import UrlRow
from app.services.live import reconcile as rc
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit


def tab(id_, url="https://arena.ai/c/1"):
    return SimpleNamespace(id=id_, title="T", url=url,
                           ws_url=f"ws://127.0.0.1:9222/devtools/page/{id_}", type="page")


class Deps(rc.LiveDeps):
    """Recorders behind the seam, with failure injection for the pool phase."""

    def __init__(self, bridge, *fetches, join_fail=(), commit_fail=0):
        super().__init__(fetch_tabs=self._fetch, join_tab=self._join, commit=self._commit, log=self._log)
        self.bridge = bridge
        self.fetches = list(fetches)
        self.join_fail = set(join_fail)
        self.commit_fail = commit_fail
        self.joined, self.commits, self.lines = [], 0, []

    async def _fetch(self):
        item = self.fetches.pop(0) if len(self.fetches) > 1 else self.fetches[0]
        if isinstance(item, Exception):
            raise item
        return item

    async def _join(self, ws):
        if ws in self.join_fail:
            raise RuntimeError(f"boom {ws}")
        self.joined.append(ws)

    def _commit(self):
        self.commits += 1
        if self.commits <= self.commit_fail:
            raise OSError("disk full")
        self.bridge._save_arena()

    def _log(self, msg, level="info"):
        self.lines.append((msg, level))


def mkenv(tmp_path, *fetches, urls=None, **kw):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge.state.urls = list(urls or [])
    env.deps = Deps(env.bridge, *fetches, **kw)
    return env


def texts(deps):
    return [m for m, _l in deps.lines]


# ── D-1: the pool phase may fail, the rebuild still lands ──


@pytest.mark.asyncio
async def test_a_failed_pool_join_still_commits_the_rebuilt_rows(tmp_path):
    old = UrlRow.create("https://arena.ai/c/1", enabled=True, tab_id="t1")
    t = tab("t1")
    env = mkenv(tmp_path, [t], urls=[old], join_fail={t.ws_url})
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert report.swept == 1 and report.added == 1
    assert [u.url for u in env.bridge.state.urls] == ["https://arena.ai/c/1"]  # rebuilt, not empty
    assert env.deps.commits == 1  # the rows reached the UI + jar anyway
    assert report.error and any("Pool join failed" in m for m in texts(env.deps))
    assert env.recs["arena_state_updated"].calls  # the push that shows the rebuilt row


@pytest.mark.asyncio
async def test_a_joining_tab_does_not_stop_the_other_joins(tmp_path):
    bad, good = tab("t1"), tab("t2", "https://arena.ai/c/2")
    env = mkenv(tmp_path, [bad, good], urls=[], join_fail={bad.ws_url})
    report = await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert env.deps.joined == [good.ws_url] and report.joined == 1
    assert any("Pool join failed" in m for m in texts(env.deps))


@pytest.mark.asyncio
async def test_a_failing_checkbox_enforcement_still_commits(tmp_path):
    """The leave half of the gate is a pool write: its failure must not skip the row write."""
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://x/t1", title="T", url="https://arena.ai/1"))
    off = UrlRow.create("https://arena.ai/1", enabled=False, tab_id="t1")
    on = UrlRow.create("https://arena.ai/2", enabled=True, tab_id="t2")
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[], pool=pool)
    env.bridge.state.urls = [off, on]
    env.deps = Deps(env.bridge, [tab("t1", "https://arena.ai/1"), tab("t2", "https://arena.ai/2"),
                                 tab("t3", "https://arena.ai/3")])
    env.deps.leave_tab = lambda tab_id: (_ for _ in ()).throw(RuntimeError("pool busy"))
    report = await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert report.error == "pool busy" and report.added == 1
    assert env.deps.commits == 1  # the new row landed even though the pool write blew up
    assert "https://arena.ai/3" in [u.url for u in env.bridge.state.urls]
    assert any("Pool update failed (pool busy)" in m for m in texts(env.deps))


@pytest.mark.asyncio
async def test_a_failed_save_is_retried_on_the_next_pass(tmp_path):
    env = mkenv(tmp_path, [tab("t1")], urls=[], commit_fail=1)
    first = await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert "disk full" in first.error and env.bridge._reconcile_unsaved is True
    assert any("URL save failed" in m for m in texts(env.deps))
    await rc.reconcile_once(env.bridge, env.deps, "auto")  # nothing changed this pass
    assert env.deps.commits == 2 and env.bridge._reconcile_unsaved is False


# ── D-2: the loop never ends by itself (I-47 shape) ──


@pytest.mark.asyncio
async def test_the_loop_survives_a_failing_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "interval_ms", lambda bridge: 0)
    env = mkenv(tmp_path, [tab("t1")], urls=[])
    real_get_state, calls = env.bridge.config.get_state, {"n": 0}

    def flaky(key, default=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("config exploded")
        return real_get_state(key, default)

    monkeypatch.setattr(env.bridge.config, "get_state", flaky)
    task = asyncio.create_task(rc.reconcile_loop(env.bridge, env.deps))
    await asyncio.sleep(0.05)
    assert not task.done(), "the loop must survive its failing pass"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rc.pass_count(env.bridge) >= 2  # the pass after the failure still ran
    assert sum(1 for m in texts(env.deps) if "loop alive" in m) == 1


def test_a_pass_error_is_logged_once_per_distinct_text(tmp_path):
    env = mkenv(tmp_path, [])
    rc._log_pass_error(env.bridge, env.deps, RuntimeError("same"))
    rc._log_pass_error(env.bridge, env.deps, RuntimeError("same"))
    rc._log_pass_error(env.bridge, env.deps, RuntimeError("other"))
    note = [m for m in texts(env.deps) if "loop alive" in m]
    assert len(note) == 2 and "same" in note[0] and "other" in note[1]


# ── D-5: an empty manual rebuild names the pattern ──


@pytest.mark.asyncio
async def test_an_empty_manual_rebuild_names_the_pattern(tmp_path):
    other = tab("t9", "https://other.example/c/9")
    dead = UrlRow.create("https://arena.ai/gone", enabled=True, tab_id="tx")
    env = mkenv(tmp_path, [other], urls=[dead])
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert env.bridge.state.urls == [] and report.swept == 1
    assert any("0 of 1 open tab(s) match pattern 'arena.ai'" in m for m in texts(env.deps))


@pytest.mark.asyncio
async def test_a_rebuilt_list_has_no_empty_note(tmp_path):
    env = mkenv(tmp_path, [tab("t1")], urls=[])
    await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert [u.url for u in env.bridge.state.urls] == ["https://arena.ai/c/1"]
    assert not any("open tab(s) match pattern" in m for m in texts(env.deps))

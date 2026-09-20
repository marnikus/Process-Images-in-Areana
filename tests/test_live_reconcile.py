"""live.reconcile — Python owns the URL-row cadence (S6, D-11 / I-50).

Real Bridge from the golden harness; `LiveDeps` carries the only fakes (tab
fetch, pool join, commit, log). The pass runs in every run state, reads its
interval every turn, never removes on an empty or failed fetch, names a reason
for every removal and ends every change in the injected `commit` + a
`wake("urls")` — never in an undo entry (system change, I-37).
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.models import UrlRow
from app.services.live import feed, reconcile, url_policy
from app.services.live.bus import live_bus
from app.ui.panels import browser_tabs as bt
from tests.characterization.harness import build_bridge, build_stack
from tests.characterization.test_batch_goldens import CORE_STACK

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def tab(id_, url="https://arena.ai/c/1"):
    return SimpleNamespace(id=id_, title="Arena", url=url, ws_url=f"ws://127.0.0.1:9222/devtools/page/{id_}", type="page")


def make_deps(tabs):
    """Fakes at the seam: `tabs` is a list (one fetch), a list of lists (per pass) or an Exception."""
    calls = SimpleNamespace(joined=[], commits=0, logs=[])
    scripted = isinstance(tabs, list) and tabs and isinstance(tabs[0], list)
    script = list(tabs) if scripted else None

    async def fetch_tabs():
        if isinstance(tabs, Exception):
            raise tabs
        return script.pop(0) if script else tabs

    async def join_tab(ws):
        calls.joined.append(ws)

    def commit(bridge):
        calls.commits += 1
        bridge._save_arena()

    deps = reconcile.LiveDeps(fetch_tabs=fetch_tabs, join_tab=join_tab, commit=commit,
                              log=lambda m, l="info": calls.logs.append(m))
    return deps, calls


def make_bridge(tmp_path, urls):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge.state.urls = list(urls)
    return env.bridge


async def test_the_interval_is_read_every_pass(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, [])
    deps, _ = make_deps([])
    waits = []
    bus = reconcile.url_bus(bridge)

    async def fake_wait(timeout_s):
        waits.append(timeout_s)
        if len(waits) == 1:
            bridge.config.set_state(url_reconcile_interval_ms=700)   # changed between passes, no restart
        if len(waits) >= 2:
            raise asyncio.CancelledError()
        return ""

    monkeypatch.setattr(bus, "wait", fake_wait)
    with pytest.raises(asyncio.CancelledError):
        await reconcile.reconcile_loop(bridge, deps)
    assert waits == [5.0, 0.7]


async def test_an_empty_or_failed_fetch_never_removes_rows(tmp_path):
    gone = UrlRow.create("https://arena.ai/c/1", tab_id="t1")
    bridge = make_bridge(tmp_path, [gone])
    deps, calls = make_deps([])
    for _ in range(3):
        report = await reconcile.reconcile_once(bridge, deps, "interval")
        assert report.removed == 0
    assert bridge.state.urls == [gone] and reconcile.reconcile_state(bridge).misses == {}
    failing, fcalls = make_deps(RuntimeError("chrome down"))
    report = await reconcile.reconcile_once(bridge, failing, "interval")
    assert report == reconcile.Report() and bridge.state.urls == [gone]
    assert fcalls.commits == 0 and any("skipped" in m for m in fcalls.logs)


async def test_a_new_tab_is_added_claimed_and_joined(tmp_path):
    unlinked = UrlRow.create("https://arena.ai/c/1")
    bridge = make_bridge(tmp_path, [unlinked])
    deps, calls = make_deps([tab("t1", "https://arena.ai/c/1"), tab("t2", "https://arena.ai/c/2"),
                             tab("t3", "https://other.example/x")])
    report = await reconcile.reconcile_once(bridge, deps, "interval")
    assert (report.added, report.linked, report.joined, report.removed) == (1, 1, 2, 0)
    assert unlinked.tab_id == "t1"
    assert [u.tab_id for u in bridge.state.urls] == ["t1", "t2"]           # the non-matching tab is ignored
    assert calls.joined == [tab("t1").ws_url, tab("t2").ws_url]             # S1's repaired pool join
    assert calls.commits == 1 and live_bus(bridge).reasons() == ["urls"]
    assert reconcile.last_pass_at(bridge) > 0 and reconcile.reconcile_state(bridge).passes == 1


async def test_a_closed_tab_is_removed_with_a_reason_and_wakes_the_loop(tmp_path):
    closed = UrlRow.create("https://arena.ai/c/1", enabled=False, tab_id="t1")
    kept = UrlRow.create("https://arena.ai/c/2", tab_id="t2")
    bridge = make_bridge(tmp_path, [closed, kept])
    bridge.state.images[0].assigned_url_id = closed.id
    deps, calls = make_deps([tab("t2", "https://arena.ai/c/2")])
    first = await reconcile.reconcile_once(bridge, deps, "interval")
    assert first.removed == 0 and len(bridge.state.urls) == 2                  # one miss: hysteresis
    second = await reconcile.reconcile_once(bridge, deps, "interval")
    assert second.removed == 1 and [r.reason for r in second.removals] == ["tab_gone"]
    assert bridge.state.urls == [kept]
    assert bridge.state.images[0].assigned_url_id is None                     # dangling assignment cleared
    assert calls.commits == 1 and "urls" in live_bus(bridge).reasons()
    assert any("https://arena.ai/c/1" in m and "tab closed" in m for m in calls.logs)
    # the tab comes back: its row returns unchecked, as the user left it
    back, _ = make_deps([tab("t1", "https://arena.ai/c/1"), tab("t2", "https://arena.ai/c/2")])
    await reconcile.reconcile_once(bridge, back, "interval")
    assert [(u.tab_id, u.enabled) for u in bridge.state.urls] == [("t2", True), ("t1", False)]


@pytest.mark.parametrize("run_state", ["idle", "running", "paused"])
async def test_reconcile_runs_in_every_run_state(tmp_path, run_state):
    bridge = make_bridge(tmp_path, [UrlRow.create("https://arena.ai/c/1", tab_id="t1")])
    bridge._run_state = run_state
    deps, _ = make_deps([tab("t2", "https://arena.ai/c/2")])
    first = await reconcile.reconcile_once(bridge, deps, "interval")
    second = await reconcile.reconcile_once(bridge, deps, "interval")
    assert (first.added, first.removed, second.removed) == (1, 0, 1)          # identical in every state
    assert [u.tab_id for u in bridge.state.urls] == ["t2"]


async def test_the_manual_slot_triggers_an_immediate_pass_through_the_same_function(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, [])
    seen = []

    async def spy(b, deps, source):
        seen.append((b, deps, source))
        return reconcile.Report()

    monkeypatch.setattr(bt, "reconcile_once", spy)
    await bt.auto_scan_pass(bridge, "manual")
    assert len(seen) == 1 and seen[0][0] is bridge and seen[0][2] == "manual"
    deps = seen[0][1]
    assert isinstance(deps, reconcile.LiveDeps)
    saves = []
    monkeypatch.setattr(bridge, "_save_arena", lambda: saves.append(1))
    deps.commit(bridge)
    assert saves == [1]


async def test_a_busy_tab_is_deferred_and_commit_pushes_no_undo(tmp_path):
    from app.browser.page_pool import PagePool
    from app.services import cooldown_service
    from tests.test_captcha_service import make_info

    pool = PagePool()
    pool.add_page(make_info("t1"))
    cooldown_service.set_tab_image(pool, "t1", "pic1.png")
    busy = UrlRow.create("https://arena.ai/c/1", tab_id="t1")
    bridge = make_bridge(tmp_path, [busy])
    bridge._page_pool = pool
    pushes = []
    bridge.undo_service.push = lambda *a, **k: pushes.append(a)
    deps, calls = make_deps([tab("t2", "https://arena.ai/c/2")])
    await reconcile.reconcile_once(bridge, deps, "interval")
    report = await reconcile.reconcile_once(bridge, deps, "interval")
    assert report.deferred == 1 and busy in bridge.state.urls              # the job finishes first (RULE 15)
    assert calls.commits >= 1 and pushes == []                             # system change: no undo entry
    quiet, qcalls = make_deps([tab("t1", "https://arena.ai/c/1"), tab("t2", "https://arena.ai/c/2")])
    await reconcile.reconcile_once(bridge, quiet, "auto")
    assert qcalls.commits == 0                                             # nothing changed ⇒ no write


def test_the_js_timer_is_gone():
    src = (ROOT / "app/ui/web/js/panels/cdp.js").read_text(encoding="utf-8")
    assert "autoConnectScan(), 15000" not in src
    assert src.count("setInterval") == 1                                   # the 500 ms ensurePrimary tick stays


async def test_start_reconciler_is_idempotent(tmp_path):
    bridge = make_bridge(tmp_path, [])
    deps, _ = make_deps([])
    assert reconcile.start_reconciler(bridge, deps) is True
    try:
        assert reconcile.start_reconciler(bridge, deps) is False           # one loop per bridge
        fut = bridge._url_reconciler
        assert fut is not None and not fut.done()
    finally:
        bridge._url_reconciler.cancel()

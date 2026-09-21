"""S6: the URL reconciler — cadence, fetch safety, add/claim/join/remove, funnel, timer gone."""

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.core.models import UrlRow
from app.services.live import reconcile as rc
from app.services.live.bus import live_bus
from tests.characterization.harness import build_bridge, build_stack


def tab(tid, url="https://arena.ai/c/x", ws=None):
    return SimpleNamespace(id=tid, title=f"T {tid}", url=url,
                           ws_url=ws or f"ws://127.0.0.1:9222/devtools/page/{tid}")


async def _noop_join(ws):
    pass


def _noop_log(m, level="info"):
    pass


def fake_deps(fetch_tabs=None):
    rec = {"fetch": 0, "join": [], "commit": 0, "log": []}

    async def _fetch():
        rec["fetch"] += 1
        return list(fetch_tabs) if fetch_tabs is not None else []

    async def _join(ws):
        rec["join"].append(ws)

    def _commit():
        rec["commit"] += 1

    def _log(m, level="info"):
        rec["log"].append((m, level))

    return rc.LiveDeps(fetch_tabs=_fetch, join_tab=_join, commit=_commit, log=_log), rec


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_interval_is_read_every_pass(tmp_path, monkeypatch):
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=[])
    bridge = env.bridge
    real_sleep = asyncio.sleep
    sleeps = []

    async def instant_sleep(d):
        sleeps.append(d)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
    box, calls = {}, []

    async def fetch():
        calls.append(1)
        if len(calls) == 2:
            bridge.config.set_state(url_reconcile_interval_ms=700)
        if len(calls) == 3:
            asyncio.get_running_loop().call_soon(box["task"].cancel)
        return []

    d = rc.LiveDeps(fetch_tabs=fetch, join_tab=_noop_join, commit=lambda: None, log=_noop_log)
    box["task"] = asyncio.create_task(rc.reconcile_loop(bridge, d))
    with contextlib.suppress(asyncio.CancelledError):
        await box["task"]
    # sleep, pass, sleep… — the 700 ms takes effect on the very next sleep
    assert sleeps == [5.0, 5.0, 0.7, 0.7]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_empty_fetch_never_removes_rows(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=["t1"])
    bridge = env.bridge
    d, rec = fake_deps(fetch_tabs=[])
    report = await rc.reconcile_once(bridge, d, "auto")
    assert report.removed == 0
    assert len(bridge.state.urls) == 1  # the row survives its first miss
    assert bridge._reconcile_misses == {"t1": 1}
    # S7: the only change is flag init ((False, "") -> (False, "offline")) — commits once
    assert rec["commit"] == 1
    assert rec["log"] == []  # auto stays silent on no-change
    await rc.reconcile_once(bridge, d, "auto")
    assert rec["commit"] == 1  # S7: flags settled, silence resumes

    async def boom():
        raise RuntimeError("cdp down")

    d2, rec2 = fake_deps()
    d2 = rc.LiveDeps(fetch_tabs=boom, join_tab=d2.join_tab, commit=d2.commit, log=d2.log)
    report2 = await rc.reconcile_once(bridge, d2, "auto")
    assert (report2.added, report2.removed) == (0, 0)
    assert any("Auto-connect scan skipped: cdp down" in m for m, _ in rec2["log"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_new_tab_is_added_claimed_and_joined(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=[])
    bridge = env.bridge
    bridge.state.urls = [UrlRow.create("https://arena.ai/c/unlinked")]  # claim target
    tabs = [tab("t2", "https://arena.ai/c/new"), tab("t3", "https://arena.ai/c/unlinked")]
    d, rec = fake_deps(fetch_tabs=tabs)
    report = await rc.reconcile_once(bridge, d, "auto")
    assert report.added == 1
    assert report.linked == 1
    assert rec["join"] == [tabs[0].ws_url, tabs[1].ws_url]
    assert live_bus(bridge).reasons() == ["urls"]
    assert rec["commit"] == 1
    by_tab = {u.tab_id: u for u in bridge.state.urls}
    assert by_tab["t2"].url == "https://arena.ai/c/new" and by_tab["t2"].enabled is True
    assert by_tab["t3"].url == "https://arena.ai/c/unlinked"  # the old row, claimed
    assert bridge._reconcile_passes == 1
    assert bridge._reconcile_last_pass_at > 0


@pytest.mark.unit
def test_claim_rows_skips_owned_and_unknown():
    mine = UrlRow.create("https://arena.ai/c/a", tab_id="t1")  # already owned
    assert rc._claim_rows({mine.id: mine}, [(mine.id, "t9"), ("nope", "t2")]) == 0
    assert mine.tab_id == "t1"
    free = UrlRow.create("https://arena.ai/c/b")
    assert rc._claim_rows({free.id: free}, [(free.id, "t2")]) == 1
    assert free.tab_id == "t2"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_closed_tab_is_removed_with_a_reason_and_wakes_the_loop(tmp_path):
    from app.browser.page_status import PageInfo
    from app.services.cooldown_service import set_tab_image
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=["t1"],
                       pool=PagePool())
    bridge = env.bridge
    bridge._reconcile_misses = {"t1": 2, "tbusy": 9}  # third miss for t1
    busy = UrlRow.create("https://arena.ai/c/busy", tab_id="tbusy")
    bridge.state.urls.append(busy)
    bridge.state.urls.append(UrlRow.create("https://arena.ai/c/dup", tab_id="t1"))  # I-33 warn path
    bridge._page_pool.add_page(PageInfo(tab_id="tbusy", ws_url="ws://x/busy",
                                        title="B", url=busy.url))
    set_tab_image(bridge._page_pool, "tbusy", "b.png")
    d, rec = fake_deps(fetch_tabs=[])
    report = await rc.reconcile_once(bridge, d, "auto")
    assert report.removed == 1
    assert [u.tab_id for u in bridge.state.urls] == ["tbusy"]  # busy survives
    assert report.deferred == 1
    assert report.stale == 1  # the pooled busy page is flagged, not deleted
    assert bridge._url_memory == {"t1": True}  # the checkbox is remembered
    assert live_bus(bridge).reasons() == ["urls"]
    assert rec["commit"] == 1
    assert any("tab_gone" in m for m, _ in rec["log"])


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("run_state", ["idle", "running", "paused"])
async def test_reconcile_runs_in_every_run_state(tmp_path, run_state):
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=["t1"])
    bridge = env.bridge
    bridge._run_state = run_state
    bridge._reconcile_misses = {"t1": 2}
    d, rec = fake_deps(fetch_tabs=[])
    report = await rc.reconcile_once(bridge, d, "auto")
    assert (report.removed, bridge.state.urls, rec["commit"]) == (1, [], 1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_manual_slot_and_reparse_buttons_trigger_an_immediate_pass(tmp_path, monkeypatch):
    import app.ui.panels.browser_tabs as bt
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=[], pool=PagePool())
    bridge = env.bridge
    real_sleep = asyncio.sleep
    sleeps = []

    async def instant_sleep(d):
        sleeps.append(d)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)
    calls, phase = [], [0]
    manual = tab("t9", "https://arena.ai/c/manual")

    async def fetch():
        calls.append(1)
        return [] if phase[0] == 0 else [manual]

    loop_deps = rc.LiveDeps(fetch_tabs=fetch, join_tab=_noop_join,
                            commit=lambda: None, log=_noop_log)
    task = asyncio.create_task(rc.reconcile_loop(bridge, loop_deps))
    for _ in range(200):
        if len(calls) >= 2:
            break
        await real_sleep(0.01)
    assert len(calls) >= 2
    joins = []

    async def manual_join(ws):
        joins.append(ws)

    async def manual_fetch():
        await real_sleep(0.05)  # the loop spins (and skips) during the manual pass
        return [manual]

    monkeypatch.setattr(bt, "fetch_open_tabs", lambda b: manual_fetch())
    monkeypatch.setattr(bt, "do_connect_page_pool", lambda b, ws: manual_join(ws))
    pool_before = len(env.recs["page_pool_updated"].calls)
    await bt.do_auto_connect_scan(bridge, "manual")
    phase[0] = 1  # no await between: the loop cannot interleave a pass here
    assert [u.tab_id for u in bridge.state.urls] == ["t9"]  # the immediate pass landed
    assert joins == [manual.ws_url]
    assert len(env.recs["page_pool_updated"].calls) == pool_before + 1  # join emits
    assert sleeps and all(s == 5.0 for s in sleeps)  # the floor never shifted
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    captured = []
    monkeypatch.setattr(bt, "schedule_coro", lambda b, coro: captured.append(coro))
    assert bridge.auto_connect_scan("manual") == "pending"
    assert len(captured) == 1
    await captured[0]
    assert [u.tab_id for u in bridge.state.urls] == ["t9"]
    # manual with nothing to do still answers
    from app.browser.page_status import PageInfo
    bridge._page_pool.add_page(PageInfo(tab_id="t9", ws_url=manual.ws_url,
                                        title="T t9", url=manual.url))
    bridge._page_pool.get_page("t9").is_connected = True
    await bt.do_auto_connect_scan(bridge, "manual")
    assert any("no changes" in m for m, _ in env.recs["arena_log"].calls)
    assert len(joins) == 2  # nothing new to join


@pytest.mark.unit
@pytest.mark.asyncio
async def test_commit_goes_through_the_single_row_funnel(tmp_path, monkeypatch):
    import app.ui.panels.browser_tabs as bt
    env = build_bridge(tmp_path, build_stack([]), n_images=0, tab_ids=[])
    bridge = env.bridge
    pushes = []
    monkeypatch.setattr(bridge.undo_service, "push", lambda *a, **k: pushes.append(a))
    saves = []
    orig_save = bridge._save_arena

    def save_and_record():
        saves.append(1)
        return orig_save()

    monkeypatch.setattr(bridge, "_save_arena", save_and_record)
    d, rec = fake_deps(fetch_tabs=[tab("t2", "https://arena.ai/c/new")])
    report = await rc.reconcile_once(bridge, d, "auto")
    assert report.added == 1 and rec["commit"] == 1  # the pass ends in deps.commit
    deps2 = bt.live_deps(bridge)  # and the real wiring is commit_urls without undo
    deps2.commit()
    assert saves == [1] and pushes == []
    assert await deps2.fetch_tabs() == []  # FakeCDP has no tabs; the fetch is wired through
    joins = []

    async def rec_join(b, ws):
        joins.append(ws)

    monkeypatch.setattr(bt, "do_connect_page_pool", rec_join)
    await deps2.join_tab("ws-x")
    assert joins == ["ws-x"]
    deps2.log("probe", "info")
    assert ("probe", "info") in env.recs["arena_log"].calls
    submitted = []
    monkeypatch.setattr(rc, "schedule_coro",
                        lambda b, coro: submitted.append(coro) or "task")
    bt.start_url_reconciler(bridge)
    bt.start_url_reconciler(bridge)
    assert len(submitted) == 1  # the second start is a no-op
    submitted[0].close()
    # a failing commit still releases the guard and logs the skip line
    async def new_tab_fetch():
        return [tab("t3", "https://arena.ai/c/three")]

    def boom_commit(b, undo=True):
        raise RuntimeError("commit down")

    monkeypatch.setattr(bt, "fetch_open_tabs", lambda b: new_tab_fetch())
    monkeypatch.setattr(bt, "commit_urls", boom_commit)
    await bt.do_auto_connect_scan(bridge, "auto")
    assert bridge._auto_scan_running is False
    assert any("scan skipped" in m for m, _ in env.recs["arena_log"].calls)


@pytest.mark.unit
def test_the_js_timer_is_gone():
    from pathlib import Path
    src = Path("app/ui/web/js/panels/cdp.js").read_text()
    assert "autoConnectScan(), 15000" not in src
    assert src.count("setInterval") == 1  # the 500 ms ensurePrimary tick

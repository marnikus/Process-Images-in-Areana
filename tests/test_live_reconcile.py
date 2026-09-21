"""S6 url reconciler — real rows, a real PagePool, injected LiveDeps (plan §S6 tests 10-17).

RED at base: `app.services.live.reconcile` / `debug_view` do not exist yet; the
`cdp.js` 15 s timer is still planted.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core.models import UrlRow
from app.services.live import reconcile as rec
from app.services.live.bus import LiveBus, live_bus
from app.services.live.reconcile import LiveDeps, Report
from app.services.live.url_policy import MISS_THRESHOLD
from app.ui.panels import browser_tabs

INTERVAL_KEY = "url_reconcile_interval_ms"


class FakeCfg:
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get_state(self, key, default=None):
        return self._data.get(key, default)

    def set_state(self, **kw):
        self._data.update(kw)


class FakeDeps:
    def __init__(self, tabs=()):
        self.tabs_data = list(tabs)
        self.joined = []
        self.commits = 0
        self.logs = []

    async def fetch_tabs(self):
        return list(self.tabs_data)

    async def join_tab(self, ws_url):
        self.joined.append(ws_url)

    def commit(self):
        self.commits += 1

    def log(self, msg, lvl="info"):
        self.logs.append((msg, lvl))

    def as_live_deps(self):
        return LiveDeps(fetch_tabs=self.fetch_tabs, join_tab=self.join_tab,
                        commit=self.commit, log=self.log)


def tab(tab_id, url="https://arena.ai/chat0", ws=None):
    return SimpleNamespace(id=tab_id, title="chat", url=url, ws_url=ws or f"ws://x/{tab_id}", type="page")


def row(url, tab_id="", enabled=True):
    return UrlRow.create(url, enabled=enabled, tab_id=tab_id)


def bridge(urls=(), **kw):
    b = SimpleNamespace(state=SimpleNamespace(urls=list(urls)),
                        config=FakeCfg(kw.pop("cfg", {"url_pattern": "arena.ai", INTERVAL_KEY: 60000})),
                        _page_pool=kw.pop("pool", None),
                        _url_misses={},
                        _url_checkbox_mem={},
                        _live_bus=LiveBus(),
                        _live_supervisor=False,
                        _run_state=kw.pop("run_state", "idle"),
                        logs=[])
    return b


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_empty_fetch_never_removes_rows():
    b = bridge([row("https://arena.ai/a", "t1")])
    deps = FakeDeps(tabs=[])
    rep = await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert rep.removed == 0
    assert [u.url for u in b.state.urls] == ["https://arena.ai/a"]

    async def boom():
        raise RuntimeError("cdp gone")

    with pytest.raises(RuntimeError):
        await rec.reconcile_once(b, LiveDeps(fetch_tabs=boom, join_tab=None, commit=None, log=None), "auto")
    assert [u.url for u in b.state.urls] == ["https://arena.ai/a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_new_tab_is_added_claimed_and_joined():
    b = bridge()
    deps = FakeDeps(tabs=[tab("t1", ws="ws://pool/t1")])
    bus = live_bus(b)
    rep = await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert isinstance(rep, Report)
    assert rep.added == 1 and rep.joined == 1
    assert deps.joined == ["ws://pool/t1"]
    assert deps.commits == 1
    assert "urls" in bus.reasons()
    assert any("+1 rows" in m for m, _ in deps.logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_unlinked_row_matching_a_live_tab_is_claimed():
    b = bridge([row("https://arena.ai/chat0", "")])
    deps = FakeDeps(tabs=[tab("t1", url="https://arena.ai/chat0")])
    rep = await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert rep.linked == 1
    assert b.state.urls[0].tab_id == "t1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_closed_tab_is_removed_with_a_reason_and_wakes_the_loop():
    b = bridge([row("https://arena.ai/a", "t1")])
    deps = FakeDeps(tabs=[tab("t9", url="https://example.com/x")])  # alive, off-pattern
    bus = live_bus(b)
    for _ in range(MISS_THRESHOLD):                        # hysteresis: two passes
        rep = await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert rep.removed == 1
    assert b.state.urls == []
    assert any("tab gone" in m for m, _ in deps.logs)
    assert "urls" in bus.reasons()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_miss_keeps_the_row():
    b = bridge([row("https://arena.ai/a", "t1")])
    deps = FakeDeps(tabs=[tab("t9", url="https://example.com/x")])
    rep = await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert rep.removed == 0 and len(b.state.urls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("run_state", ["idle", "running", "paused"])
async def test_reconcile_runs_in_every_run_state(run_state):
    b = bridge(run_state=run_state)
    deps = FakeDeps(tabs=[tab("t1")])
    rep = await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert rep.added == 1                       # identical behavior in every state


@pytest.mark.unit
@pytest.mark.asyncio
async def test_commit_goes_through_the_single_row_funnel_without_undo():
    # the fake bridge has NO undo_service at all: any undo push would explode (RULE 8)
    b = bridge()
    deps = FakeDeps(tabs=[tab("t1")])
    await rec.reconcile_once(b, deps.as_live_deps(), "auto")
    assert deps.commits == 1                    # one commit per changing pass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remembered_checkbox_survives_a_close_reopen_cycle():
    b = bridge([row("https://arena.ai/a", "t1", enabled=False)])
    gone = FakeDeps(tabs=[tab("t9", url="https://example.com/x")])
    depsg = gone.as_live_deps()
    for _ in range(MISS_THRESHOLD):
        await rec.reconcile_once(b, depsg, "auto")
    back = FakeDeps(tabs=[tab("t7", url="https://arena.ai/a")])
    rep = await rec.reconcile_once(b, back.as_live_deps(), "auto")
    assert rep.added == 1
    assert b.state.urls[0].enabled is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_interval_is_read_every_pass(monkeypatch):
    from app.services.live import debug_view
    b = bridge(cfg={"url_pattern": "arena.ai", INTERVAL_KEY: 60000})
    deps = FakeDeps(tabs=[])

    async def boom():
        raise RuntimeError("cdp gone — pass fails loud but the loop survives")

    deps.fetch = deps.as_live_deps().fetch_tabs
    dead = LiveDeps(fetch_tabs=boom, join_tab=deps.join_tab, commit=deps.commit, log=deps.log)
    calls = []
    real_interval_ms = debug_view.interval_ms

    def spy_interval_ms(bridge):
        calls.append(bridge.config.get_state(INTERVAL_KEY))
        return real_interval_ms(bridge)

    monkeypatch.setattr(debug_view, "interval_ms", spy_interval_ms)
    task = asyncio.create_task(rec.reconcile_loop(b, dead))   # pass 1 crashes pass, waits 60 s
    await asyncio.sleep(0.05)
    assert b.config is not None
    live_bus(b).wake("urls")                                   # wake → pass 2 (still crashing)
    await asyncio.sleep(0.05)
    b.config.set_state(**{INTERVAL_KEY: 500})                  # now shorten
    live_bus(b).wake("urls")                                   # wake → pass 3, then waits 0.5 s
    await asyncio.sleep(0.05)
    started_at = asyncio.get_running_loop().time()
    live_bus(b).wake("urls")                                   # wake → pass 4, previous wait irrelevant
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls and all(v in (500, 60000) for v in calls)
    assert calls[-1] == 500, "the interval is read fresh every pass, not cached at start"
    assert 60000 in calls[:3]                                  # the long wait was entered first
    assert asyncio.get_running_loop().time() - started_at < 1.5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_loop_survives_a_failing_pass_and_logs_loudly():
    b = bridge()
    deps = FakeDeps()
    async def boom():
        raise RuntimeError("cdp gone")
    dead = LiveDeps(fetch_tabs=boom, join_tab=deps.join_tab, commit=deps.commit, log=deps.log)
    task = asyncio.create_task(rec.reconcile_loop(b, dead))
    await asyncio.sleep(0.05)
    live_bus(b).wake("urls")
    await asyncio.sleep(0.05)
    assert not task.done()                                     # loop is still alive
    assert any("reconcile" in m.lower() for m, lvl in deps.logs if lvl == "warn")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_manual_trigger_does_not_reset_the_loops_countdown():
    b = bridge(cfg={"url_pattern": "arena.ai", INTERVAL_KEY: 1000})
    deps = FakeDeps(tabs=[])
    task = asyncio.create_task(rec.reconcile_loop(b, deps.as_live_deps()))
    await asyncio.sleep(0.05)
    await rec.reconcile_once(b, deps.as_live_deps(), "manual")
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert rec.last_pass_at(b) > 0                             # the manual pass IS recorded


@pytest.mark.unit
def test_the_js_timer_is_gone():
    src = open("app/ui/web/js/panels/cdp.js", encoding="utf-8").read()
    assert "autoConnectScan(), 15000" not in src
    assert src.count("setInterval") == 1      # only the 500 ms ensurePrimary tick stays

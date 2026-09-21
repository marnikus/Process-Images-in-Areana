"""Worker-id overlay on pooled tabs (D-4/D-5).

Builder: one attribute-tagged, idempotent, top-middle, click-transparent div
showing `#<n>` and the full tab id. Service: `assert_badges(pool)` pushes it
into every connected page that has a CDP client, swallowing per-page errors;
the pool join and every reconciler pass call it, removal clears it.

RED at base: `ModuleNotFoundError: app.browser.worker_badge`.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser import worker_badge as wb
from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
import re

from app.browser import dom_highlight as dh
from app.services.live import worker_badges as svc

pytestmark = pytest.mark.unit


class FakeClient:
    def __init__(self, fail: bool = False):
        self.calls, self.fail = [], fail

    async def evaluate(self, js: str):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(js)
        return "ok"


def pool_of(*tabs, clients=True):
    pool = PagePool(logger=lambda m, l="info": None)
    for tid in tabs:
        pool.add_page(PageInfo(tab_id=tid, ws_url=f"ws://x/{tid}", is_connected=True))
        if clients:
            pool.register_client(tid, FakeClient(), object())
    return pool


# ── builder ───────────────────────────────────────────────────────────


def test_badge_js_shows_number_and_full_id_top_middle():
    js = wb.build_worker_badge_js(wb.WorkerBadgeSpec(worker_no=2, tab_id="ABCDEF0123456789"))
    assert wb.WORKER_ATTR in js and "#2" in js and "ABCDEF0123456789" in js
    assert "position:fixed" in js and "top:" in js and "left:50%" in js and "translateX(-50%)" in js
    assert "pointer-events:none" in js  # never eats a click
    watcher_z = int(re.search(r"z-index:(\d+)", dh.build_watcher_clear_js() + dh.build_watcher_overlay_js_from_spec(dh.WatcherOverlaySpec(kind="captcha"))).group(1))
    assert f"z-index:{wb.BADGE_Z}" in js and wb.BADGE_Z < watcher_z  # the wait popup still wins


def test_badge_js_is_idempotent_and_escapes_its_text():
    js = wb.build_worker_badge_js(wb.WorkerBadgeSpec(worker_no=1, tab_id='x"<b>'))
    assert js.count(f"[{wb.WORKER_ATTR}]") >= 1 and ".remove()" in js  # replace the previous one
    assert "textContent" in js and "<b>" not in js.split("textContent", 1)[1].split(";", 1)[0]
    assert "innerHTML" not in js


def test_clear_js_removes_only_the_badge():
    js = wb.build_worker_badge_clear_js()
    assert f"[{wb.WORKER_ATTR}]" in js and ".remove()" in js
    assert "data-arena-watcher" not in js


def test_payload_registry_parses_the_badge_js():
    from tests.test_js_payload_syntax import payloads
    keys = payloads()
    assert "worker_badge" in keys and "worker_badge_clear" in keys


# ── service ───────────────────────────────────────────────────────────


def test_assert_badges_pushes_one_badge_per_connected_page_with_a_client():
    pool = pool_of("a", "b")
    pool.get_page("b").is_connected = False
    shown = asyncio.run(svc.assert_badges(pool))
    assert shown == 1
    (a_client,) = pool.get_clients("a")[:1]
    assert len(a_client.calls) == 1 and "#1" in a_client.calls[0] and '"a"' in a_client.calls[0]
    assert pool.get_clients("b")[0].calls == []


def test_assert_badges_skips_pages_without_a_client_and_survives_errors():
    pool = pool_of("a", "b", "c", clients=False)
    pool.register_client("a", FakeClient(fail=True), object())
    pool.register_client("c", FakeClient(), object())
    assert asyncio.run(svc.assert_badges(pool)) == 1
    assert asyncio.run(svc.assert_badges(None)) == 0
    no_clients = SimpleNamespace(_pages={"a": PageInfo(tab_id="a", is_connected=True)})  # no get_clients at all
    assert asyncio.run(svc.assert_badges(no_clients)) == 0


def test_clear_badge_evaluates_the_clear_js_only_when_a_client_exists():
    client = FakeClient()
    assert asyncio.run(svc.clear_badge(client, "a")) is True
    assert wb.WORKER_ATTR in client.calls[-1] and "data-arena-watcher" not in client.calls[-1]
    assert asyncio.run(svc.clear_badge(None, "zz")) is False
    assert asyncio.run(svc.clear_badge(FakeClient(fail=True), "a")) is False  # swallowed, reported as not cleared


# ── wiring ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pool_join_asserts_the_badge_immediately(monkeypatch):
    from tests.test_page_pool_join import Host
    from app.ui.panels import page_pool as panel
    from app.ui.panels.page_pool import do_connect_page_pool

    async def fake_connect(bridge, ws_url):
        return FakeClient()

    async def fake_info(bridge, tab_id, ws_url):
        return "T", "https://arena.ai"

    monkeypatch.setattr(panel, "connect_pool_client", fake_connect)
    monkeypatch.setattr(panel, "resolve_tab_info", fake_info)
    monkeypatch.setattr(panel, "restore_page_state", lambda bridge, tab_id: None)
    monkeypatch.setattr("app.browser.cdp_arena.CDPArenaController", lambda client, log_callback: object())
    host = Host(PagePool())
    await do_connect_page_pool(host, "ws://x/devtools/page/t9")
    calls = host._page_pool.get_clients("t9")[0].calls
    assert len(calls) == 1 and wb.WORKER_ATTR in calls[0] and "#1" in calls[0]


def test_disconnect_clears_the_badge_with_the_client_captured_before_removal(monkeypatch):
    from tests.test_page_pool_join import Host
    from app.ui.panels import page_pool as panel
    pool = pool_of("a")
    client = pool.get_clients("a")[0]
    scheduled = []
    monkeypatch.setattr(panel, "schedule_coro", lambda bridge, coro: scheduled.append(coro))
    host = Host(pool)
    assert '"ok": true' in host.disconnect_page_pool("a")
    assert host._page_pool.get_page("a") is None and pool.get_clients("a") == (None, None)
    assert len(scheduled) == 1
    assert asyncio.run(scheduled[0]) is True  # runs later on the bg loop — the client was captured in time
    assert wb.WORKER_ATTR in client.calls[-1]
    assert '"ok": false' in host.disconnect_page_pool("a") and scheduled[1:] == []  # no client → nothing scheduled


@pytest.mark.asyncio
async def test_a_reconcile_pass_reasserts_badges(tmp_path, monkeypatch):
    from tests.test_live_reconcile import env_with, tab
    from app.services.live import reconcile as rc
    env = env_with(tmp_path, [tab("t1")])
    env.bridge._page_pool = pool_of("t1")
    await rc.reconcile_once(env.bridge, env.deps.as_deps(), "auto")
    calls = env.bridge._page_pool.get_clients("t1")[0].calls
    assert len(calls) == 1 and wb.WORKER_ATTR in calls[0]

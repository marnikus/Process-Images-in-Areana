"""Reparse = delete every URL row and rebuild from open tabs (2026-09-27 owner report).

"reparse in url list should delete all url and reparse it from scratch. now
it is not." Three ways the old pass failed that promise:

* a click while an automatic pass was in flight was silently dropped
  (`_auto_scan_running` → "busy", nothing queued);
* a listing that answered EMPTY (every tab closed) never reached the sweep
  ("an empty fetch never touches rows" — right for auto passes only);
* a stale live-job flag on a pooled page kept its row forever, even with no
  run live.

RED at base: all three keep the old rows.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services.cooldown_service import set_tab_image
from app.services.live import reconcile as rc
from tests.test_reparse_pool_gate import mkenv, tab

pytestmark = pytest.mark.unit


def row(n, enabled=True):
    return UrlRow.create(f"https://arena.ai/c/{n}", enabled=enabled, tab_id=f"t{n}")


@pytest.mark.asyncio
async def test_a_click_during_a_running_pass_is_queued_then_runs(tmp_path):
    old = row(1)
    env = mkenv(tmp_path, [tab("t1")], urls=[old])
    env.bridge._auto_scan_running = True            # an automatic pass is in flight
    busy = await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert busy.error == "busy"
    assert any("Reparse queued" in m for m in env.deps.lines)
    env.bridge._auto_scan_running = False           # ... that pass ends:
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    (fresh,) = env.bridge.state.urls
    assert fresh.id != old.id and fresh.url == old.url   # the queued Reparse ran
    assert any(m.startswith("🧹 Reparse: cleared 1") for m in env.deps.lines)
    assert not getattr(env.bridge, "_reparse_queued", False)


@pytest.mark.asyncio
async def test_an_auto_click_during_a_pass_is_not_queued(tmp_path):
    env = mkenv(tmp_path, [tab("t1")], urls=[row(1)])
    env.bridge._auto_scan_running = True
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert not getattr(env.bridge, "_reparse_queued", False)


@pytest.mark.asyncio
async def test_reparse_on_an_answered_empty_listing_deletes_every_row(tmp_path):
    env = mkenv(tmp_path, [], urls=[row(1), row(2, enabled=False)])
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    assert env.bridge.state.urls == [] and report.swept == 2


@pytest.mark.asyncio
async def test_an_auto_pass_on_an_empty_listing_still_never_removes(tmp_path):
    linked = row(1)
    env = mkenv(tmp_path, [], urls=[linked])
    await rc.reconcile_once(env.bridge, env.deps, "auto")
    assert env.bridge.state.urls == [linked]


@pytest.mark.asyncio
async def test_a_stale_job_flag_without_a_live_run_does_not_keep_the_row(tmp_path):
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="t1", ws_url=tab("t1").ws_url, title="T",
                           url="https://arena.ai/c/1"))
    set_tab_image(pool, "t1", "left-over.png")      # a run ended without clearing it
    old = row(1)
    env = mkenv(tmp_path, [tab("t1")], urls=[old], pool=pool)
    assert env.bridge._run_state == "idle"
    report = await rc.reconcile_once(env.bridge, env.deps, "manual")
    (fresh,) = env.bridge.state.urls
    assert fresh.id != old.id and report.swept == 1

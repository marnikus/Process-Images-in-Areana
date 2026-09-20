# Integration/contract lane: real collaborators; not counted as function units.
"""Regression coverage for the existing live/pool seams exercised by S8's shell.

These are equivalence tests, not S8 feature RED tests. Only external effects
(CDP, scheduling, signal receivers) are doubled; panel functions run unchanged.
"""
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock


from app.core.models import AppState, UrlRow
from app.ui.panels import browser_tabs, layout_state, page_pool, url_queue

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_live_deps_fetch_join_commit_and_log_use_their_real_paths(monkeypatch):
    from app.browser.page_pool import PagePool
    from app.services.live.bus import live_bus
    tab = NS(id="t1", title="Arena", url="https://arena.ai/a", ws_url="ws://test/devtools/page/t1")
    client = Mock()
    monkeypatch.setattr(page_pool, "connect_pool_client", AsyncMock(return_value=client))
    bridge = NS(cdp=NS(fetch_tabs=AsyncMock(return_value=[tab])), _page_pool=PagePool(),
                _save_arena=Mock(), _emit_arena_state=Mock(), _emit_pool_status=Mock(), _log=Mock())
    deps = browser_tabs.live_deps(bridge)
    assert await deps.fetch_tabs() == [tab]
    await deps.join_tab(tab.ws_url)
    assert bridge._page_pool.get_page("t1") is not None
    bridge._emit_pool_status.assert_called_once()
    deps.commit()
    bridge._save_arena.assert_called_once()
    bridge._emit_arena_state.assert_called_once()
    assert "urls" in live_bus(bridge).reasons()
    deps.log("reconciled")
    bridge._log.assert_called_with("reconciled", "info")


def test_live_deps_commit_and_log_tolerate_unavailable_notifications():
    bridge = NS(_save_arena=Mock(), _emit_arena_state=Mock(),
                _live_bus=NS(wake=Mock(side_effect=RuntimeError("loop closed"))),
                _log=Mock(side_effect=RuntimeError("UI closed")))
    deps = browser_tabs.live_deps(bridge)
    deps.commit()
    deps.log("reconciled")
    bridge._save_arena.assert_called_once()
    bridge._emit_arena_state.assert_called_once()
    bridge._live_bus.wake.assert_called_once_with("urls")
    bridge._log.assert_called_once_with("reconciled", "info")


def test_boot_starts_exactly_one_reconciler_through_the_scheduler(monkeypatch):
    from app.services.live import reconcile
    scheduled = []

    def schedule(bridge, coro):
        scheduled.append((bridge, coro.cr_code.co_name))
        coro.close()

    monkeypatch.setattr(reconcile, "schedule_coro", schedule)
    bridge = NS()
    browser_tabs.start_url_reconciler(bridge)
    browser_tabs.start_url_reconciler(bridge)
    assert scheduled == [(bridge, "reconcile_loop")]
    assert bridge._reconcile_started is True


def test_progress_emit_survives_broken_cadence_and_retains_a_positive_control():
    bridge = NS(state=AppState(), arena_state_updated=NS(emit=Mock()),
                progress_updated=NS(emit=Mock()), _reconcile_passes=3)
    layout_state.emit_arena_state(bridge)
    payload = json.loads(bridge.progress_updated.emit.call_args.args[0])
    assert payload["live"]["passes"] == 3
    bridge._reconcile_passes = "broken counter"
    layout_state.emit_arena_state(bridge)
    assert bridge.progress_updated.emit.call_count == 2
    payload = json.loads(bridge.progress_updated.emit.call_args.args[0])
    assert "live" not in payload
    assert payload["run_state"] == "idle"
    assert bridge.arena_state_updated.emit.call_count == 2


def test_receiver_read_failure_does_not_prevent_url_save():
    class UnavailableState:
        @property
        def urls(self):
            raise RuntimeError("state unavailable")

    bridge = NS(state=UnavailableState(), _save_arena=Mock())
    assert url_queue._recompute_receivers(bridge) == 0
    url_queue.commit_urls(bridge)
    bridge._save_arena.assert_called_once()


def test_persisted_invalid_url_reports_error_and_saves_it():
    row = UrlRow.create("not-a-url")
    bridge = NS(state=NS(urls=[row]), _save_arena=Mock())
    result = json.loads(url_queue.UrlQueueMixin.test_url(bridge, row.id))
    assert result == {"ok": False, "error": "Invalid URL"}
    assert row.last_status == "error"
    assert row.error == "Invalid URL"
    bridge._save_arena.assert_called_once()


def test_unavailable_url_presets_are_an_empty_list():
    getter = Mock(side_effect=OSError("storage unavailable"))
    bridge = NS(config=NS(presets=NS(get_url_presets=getter)))
    assert json.loads(url_queue.UrlQueueMixin.get_url_presets(bridge)) == []
    getter.assert_called_once()


@pytest.mark.asyncio
async def test_tab_fetch_distinguishes_empty_tabs_from_transport_failure():
    bridge = NS(cdp=NS(fetch_tabs=AsyncMock(return_value=[]),
                       diagnose_sync=Mock(side_effect=OSError("diagnostic unavailable"))),
                tabs_received=NS(emit=Mock()), _log=Mock())
    await browser_tabs.do_fetch_tabs(bridge)
    bridge.tabs_received.emit.assert_called_once_with("[]")
    bridge.cdp.diagnose_sync.assert_called_once()
    bridge._log.assert_not_called()
    bridge.cdp.fetch_tabs.side_effect = OSError("Chrome disconnected")
    await browser_tabs.do_fetch_tabs(bridge)
    bridge.tabs_received.emit.assert_called_once_with("[]")
    bridge._log.assert_called_once_with("❌ Tab fetch failed: Chrome disconnected", "error")

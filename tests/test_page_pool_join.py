"""S1 — L-1: `connect_page_pool` must schedule on the real scheduler helper.

RED-first (tdd-interfaces.md §S1): tests 1-2 fail at base because
`page_pool.py:147` calls `self._schedule_coro(...)` — an attribute no
production object has (the slot's `except` swallows the AttributeError, so
every pool join through the slot dies as `{"ok": false}`). The hosts below
are built WITHOUT `_schedule_coro` on purpose — L-6: the attribute injected
by test fakes is what masked the defect (D-27).

Tests 3-4 are equivalence: green at base, they pin the reply vocabulary the
JS parses and prove the coroutine S1 schedules is the one that joins the pool.
"""

import json
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.persistence.config_manager import ConfigManager
from app.ui.panels import page_pool as pp_mod
from app.ui.panels.page_pool import PagePoolMixin, do_connect_page_pool

from tests.test_panel_slots import make_host

pytestmark = pytest.mark.unit

PANEL_SRC = Path(__file__).resolve().parent.parent / "app" / "ui" / "panels" / "page_pool.py"


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)

    def connect(self, *args, **kwargs):
        pass


class Spy:
    """Records (bridge, coro) pairs; deliberately does NOT run the coro."""

    def __init__(self):
        self.calls = []

    def __call__(self, bridge, coro):
        self.calls.append((bridge, coro))


def make_pool_host(cfg, pool=None, **extra):
    """A mixin host shaped like production: NO `_schedule_coro` attribute."""
    updated = Emitter()
    host, _ = make_host(
        (PagePoolMixin,),
        _page_pool=pool if pool is not None else PagePool(),
        config=cfg,
        page_pool_updated=updated,
        _emit_pool_status=lambda: updated.emit("pool"),
        _persist_cooldowns=lambda: None,
        **extra,
    )
    return host, updated


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def test_connect_page_pool_schedules_on_the_real_helper(cfg, monkeypatch):
    """RED at base: the slot dies on the missing `_schedule_coro` attribute."""
    host, _ = make_pool_host(cfg)
    spy = Spy()
    monkeypatch.setattr(pp_mod, "schedule_coro", spy, raising=False)
    reply = json.loads(host.connect_page_pool("ws://127.0.0.1:9222/devtools/page/t1"))
    assert reply == {"ok": True}
    assert len(spy.calls) == 1
    assert spy.calls[0][0] is host
    coro = spy.calls[0][1]
    assert coro.cr_code.co_name == "do_connect_page_pool"
    coro.close()


def test_no_private_scheduler_survives_in_the_pool_panel():
    """Source lock: keeps L-6's private-scheduler double from coming back."""
    text = PANEL_SRC.read_text(encoding="utf-8")
    assert "_schedule_coro" not in text
    assert "schedule_coro(self," in text


def test_connect_page_pool_error_branches_unchanged(cfg):
    """Equivalence: the guard replies the JS already parses (RULE 4)."""
    empty = make_host((PagePoolMixin,), _page_pool=None, config=cfg,
                      page_pool_updated=Emitter(),
                      _emit_pool_status=lambda: None,
                      _persist_cooldowns=lambda: None)[0]
    assert json.loads(empty.connect_page_pool("ws://x/1")) == {
        "ok": False, "error": "pool not initialized"}
    host, _ = make_pool_host(cfg)
    assert json.loads(host.connect_page_pool("")) == {"ok": False, "error": "empty ws_url"}


def test_connect_page_pool_reports_scheduler_failure_honestly(cfg, monkeypatch):
    """A broken scheduler surfaces as error JSON, never a silent ok (RULE 4)."""
    def boom(bridge, coro):
        coro.close()
        raise RuntimeError("bg loop down")

    monkeypatch.setattr(pp_mod, "schedule_coro", boom, raising=False)
    host, _ = make_pool_host(cfg)
    assert json.loads(host.connect_page_pool("ws://x/1")) == {
        "ok": False, "error": "bg loop down"}


async def test_scheduled_coroutine_joins_the_pool(cdp_server, cfg, monkeypatch):
    """Equivalence: the coroutine S1 schedules really joins the pool.

    RULE 8: the real `connect_pool_client` runs over the fake-websocket
    boundary (`cdp_server`); only the tab-identity lookup is faked.
    """
    async def resolved(bridge, tab_id, ws_url):
        return "T", "https://arena.ai"

    monkeypatch.setattr(pp_mod, "resolve_tab_info", resolved)
    host, updated = make_pool_host(cfg)
    await do_connect_page_pool(host, "ws://127.0.0.1:9222/devtools/page/t9")
    page = host._page_pool.get_page("t9")
    assert page is not None and page.title == "T"
    assert host._page_pool.get_clients("t9")[0] is not None
    assert len(updated.calls) == 1

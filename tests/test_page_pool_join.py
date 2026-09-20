"""S1 regression for L-1: pool join uses the real scheduling seam.

`PagePoolMixin.connect_page_pool` must schedule `do_connect_page_pool` through
`app.services.run_state.schedule_coro` — the module-level service seam — and not
through a `self._schedule_coro` attribute no production object has (the slot's
`except` turned that AttributeError into `{ok: false}` for every caller).
"""

import json
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.ui.panels import page_pool
from app.ui.panels.page_pool import PagePoolMixin, do_connect_page_pool

from tests.test_panel_slots import make_host

pytestmark = pytest.mark.unit


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)

    def connect(self, *args, **kwargs):
        pass


_NO_POOL = object()


def make_pool_host(pool=_NO_POOL, **extra):
    if pool is _NO_POOL:
        pool = PagePool()
    return make_host((PagePoolMixin,), _page_pool=pool,
                     page_pool_updated=Emitter(), **extra)


def test_connect_page_pool_schedules_on_the_real_helper(monkeypatch):
    """The slot delegates to the service scheduler (no private attribute)."""
    host, _ = make_pool_host()
    assert not hasattr(host, "_schedule_coro")  # the point: prod has none
    scheduled = []

    def spy(bridge, coro):
        scheduled.append((bridge, coro))

    monkeypatch.setattr(page_pool, "schedule_coro", spy, raising=False)
    try:
        reply = json.loads(host.connect_page_pool(
            "ws://127.0.0.1:9222/devtools/page/t1"))
    finally:
        for _, coro in scheduled:
            coro.close()
    assert reply == {"ok": True}
    assert len(scheduled) == 1
    assert scheduled[0][0] is host
    assert scheduled[0][1].cr_code.co_name == "do_connect_page_pool"


def test_no_private_scheduler_survives_in_the_pool_panel():
    """Source lock: L-6's masking attribute must never come back."""
    text = Path("app/ui/panels/page_pool.py").read_text(encoding="utf-8")
    assert "_schedule_coro" not in text
    assert "schedule_coro(self," in text


def test_connect_page_pool_error_branches_unchanged():
    """Equivalence (green at base): the reply vocabulary JS parses."""
    host, _ = make_pool_host()
    assert json.loads(host.connect_page_pool("")) == \
        {"ok": False, "error": "empty ws_url"}
    nopool, _ = make_pool_host(pool=None)
    assert json.loads(nopool.connect_page_pool("ws://x/devtools/page/t1")) == \
        {"ok": False, "error": "pool not initialized"}


async def test_scheduled_coroutine_joins_the_pool(monkeypatch, isolated_config_dir):
    """Equivalence (green at base): the scheduled coroutine does the join."""
    from app.persistence.config_manager import ConfigManager

    async def fake_connect(bridge, ws_url):
        return object()

    async def fake_resolve(bridge, tab_id, ws_url):
        return "T", "https://arena.ai"

    monkeypatch.setattr(page_pool, "connect_pool_client", fake_connect)
    monkeypatch.setattr(page_pool, "resolve_tab_info", fake_resolve)
    emitted = []
    host, _ = make_pool_host(config=ConfigManager(str(isolated_config_dir)),
                             _emit_pool_status=lambda: emitted.append(1))
    await do_connect_page_pool(host, "ws://127.0.0.1:9222/devtools/page/t9")
    page = host._page_pool.get_page("t9")
    assert page is not None and page.title == "T"
    assert len(emitted) >= 1

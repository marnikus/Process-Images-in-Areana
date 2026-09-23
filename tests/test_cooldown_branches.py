"""D4.4: cooldown_service fault-tolerance branches (broken pools/getters).

The service degrades gracefully around a damaged pool or session store —
each except/fallback arm is exercised with a raising fake. RULE 8: real
service under test; only the pool boundary is faked.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services.cooldown_service import (
    _safe_int,
    add_rate_limit_penalty,
    cooldown_aware_timeout,
    edit_cooldown,
    ensure_pool_page,
    force_reset_page,
    is_tab_aborted,
    load_config,
    longest_remaining,
    note_rate_limit_event,
    refresh_expired,
    remaining_for,
    request_tab_abort,
    resolve_primary_tab,
    reset_cooldown,
    restore_cooldown_entry,
    tab_has_live_job,
)

pytestmark = pytest.mark.unit


class _RaisingLock:
    def __enter__(self):
        raise RuntimeError("lock down")

    def __exit__(self, *args):
        return False


class BrokenPool:
    _lock = _RaisingLock()
    _pages = {}

    def get_page(self, tab_id):
        raise RuntimeError("boom")

    def add_page(self, info):
        raise RuntimeError("boom")

    def status_snapshot(self):
        raise RuntimeError("boom")


def test_safe_int_and_load_config_forgive_bad_getters():
    def boom(key, default=None):
        raise RuntimeError("store down")
    assert _safe_int(boom, "cooldown_min_seconds", 300) == 300
    cfg = load_config(boom)
    assert cfg.enabled is True  # fails open
    assert cfg.min_seconds == 300
    assert _safe_int(lambda k, d=0: "junk", "x", 55) == 55  # unclamped garbage → default


def test_ensure_pool_page_guards():
    info = PageInfo(tab_id="t1", ws_url="ws://x", title="A", url="u")
    assert ensure_pool_page(None, info) is False
    assert ensure_pool_page(PagePool(), PageInfo(ws_url="ws://x")) is False  # no tab id
    assert ensure_pool_page(BrokenPool(), info) is False  # get_page raises
    broken = BrokenPool()

    class NoAdd(broken.__class__):  # get_page ok, add_page raises
        def get_page(self, tab_id):
            return None
        add_page = broken.add_page
    assert ensure_pool_page(NoAdd(), info) is False


class _PlainLock:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class AttrPool:
    """Working lock, but _pages raises AttributeError (the caught arm)."""
    _lock = _PlainLock()

    @property
    def _pages(self):
        raise AttributeError("pages gone")


def test_pool_ops_fail_closed_on_broken_pool():
    broken = BrokenPool()
    assert request_tab_abort(broken, "t1") is False
    assert is_tab_aborted(broken, "t1") is False
    assert tab_has_live_job(broken, "t1") is False
    # reset_cooldown/edit_cooldown are unguarded by design (lock is a hard invariant)
    assert force_reset_page(AttrPool(), "t1") is False
    assert resolve_primary_tab(broken, "t1") == "t1"  # snapshot down → keep preference
    assert resolve_primary_tab(None, "t9") == "t9"
    assert restore_cooldown_entry(broken, "t1", {"cooldown_until": 1}) is False
    pool = PagePool()
    assert restore_cooldown_entry(pool, "missing", {"cooldown_until": 1}) is False


def test_tab_resolution_paths():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="ta", ws_url="ws://a", title="A", url="u"))
    pool.add_page(PageInfo(tab_id="tb", ws_url="ws://b", title="B", url="u"))
    assert resolve_primary_tab(pool, "") == ""  # multiple, no preference
    assert resolve_primary_tab(pool, "ta") == "ta"  # free preferred kept
    assert resolve_primary_tab(pool, "tx") == "ta"  # unknown heals to best ready
    # allowed restriction: preference outside the checked set moves on
    assert resolve_primary_tab(pool, "ta", allowed={"tb"}) == "tb"
    assert resolve_primary_tab(pool, "ta", allowed={"tx"}) == ""  # nothing checked usable


def test_rate_limit_penalty_paths():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://a", title="A", url="u"))

    class BadCfg:
        def get_state(self, key, default=None):
            raise RuntimeError("cfg down")
    from types import SimpleNamespace
    bridge = SimpleNamespace(config=BadCfg(), _log=lambda m, l="info": None,
                             config_path=None)

    class NoPersist:
        def get_state(self, key, default=None):
            return default
    bridge2 = SimpleNamespace(config=NoPersist(), _log=lambda m, l="info": None)
    assert note_rate_limit_event(None, "t1", bridge2) == 0  # no pool
    assert note_rate_limit_event(pool, "ghost", bridge2) == -1  # unknown tab
    assert note_rate_limit_event(pool, "t1", bridge) == 1  # cfg down → default penalty
    assert pool.get_page("t1").rate_limit_count == 1
    # cooling page absorbs the penalty into the live timer
    page = pool.get_page("t1")
    page.status = PageStatus.COOLDOWN
    page.cooldown_until = 9999999999.0
    page.cooldown_total = 120
    before = page.cooldown_until
    assert add_rate_limit_penalty(pool, "t1", 60) == 2
    assert page.cooldown_until > before
    assert add_rate_limit_penalty(pool, "ghost", 60) == -1
    # a resting page (no timer left) starts cooling at once (D0-1) instead of
    # banking an invisible debt
    page.status = PageStatus.STEADY
    page.cooldown_until = 0.0
    assert add_rate_limit_penalty(pool, "t1", 60) == 3
    assert page.is_cooling() and page.pending_penalty == 0


def test_refresh_and_timeout_arms():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t1", ws_url="ws://a", title="A", url="u"))
    assert refresh_expired(pool) == []  # steady page: nothing to expire

    class BadPage:
        status = PageStatus.COOLDOWN

        def try_expire(self, now=None):
            raise RuntimeError("expire down")

        def remaining_seconds(self, now=None):
            raise RuntimeError("remaining down")
    broken_page_pool = PagePool()
    broken_page_pool._pages["bx"] = BadPage()
    assert refresh_expired(broken_page_pool) == []  # per-page error → continue
    assert longest_remaining(broken_page_pool) == 0
    assert cooldown_aware_timeout(BrokenPool(), default_sec=600.0) == 600.0
    # healthy pool: max(default, longest + 60s margin)
    assert cooldown_aware_timeout(pool, default_sec=10.0) == 60.0

    assert remaining_for(pool, "ghost") == -1
    assert remaining_for(broken_page_pool, "bx") == 0

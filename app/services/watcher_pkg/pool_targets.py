"""Build named watcher targets from the active worker pool."""
from __future__ import annotations

from app.services.watcher_pkg.targets import WatcherTarget


def get_watcher_cdp_controller(bridge):
    """Legacy primary controller (None when unconnected/failing)."""
    try:
        if not bridge.cdp or not getattr(bridge.cdp, "is_connected", False):
            return None
        from app.browser.cdp_arena import CDPArenaController
        return CDPArenaController(bridge.cdp, log_callback=lambda msg: bridge._log(msg, "info"))
    except Exception:
        return None


def _pool_page_ids(pool):
    with pool._lock:
        return list(pool._pages)


def _pool_controller(bridge, pool, tab_id):
    client, ctrl = pool.get_clients(tab_id)
    from app.browser.page_pool import tab_label_of
    if client is not None and ctrl is None:
        from app.browser.cdp_arena import CDPArenaController
        ctrl = CDPArenaController(client, log_callback=lambda message: bridge._log(message, "info"))
    return WatcherTarget(tab_id, tab_label_of(pool, tab_id), ctrl)


def _pool_targets(bridge, pool, page_ids):
    return [_pool_controller(bridge, pool, tab_id) for tab_id in page_ids]


def _primary_target(bridge):
    controller = get_watcher_cdp_controller(bridge)
    if controller is None:
        return []
    tab_id = str(getattr(bridge.cdp, "_current_tab_id", "") or "primary")
    return [WatcherTarget(tab_id, tab_id[:12], controller)]


def get_watcher_targets(bridge):
    """Include disconnected pool members as named unknown targets, never as clear."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return _primary_target(bridge)
    try:
        page_ids = _pool_page_ids(pool)
        targets = _pool_targets(bridge, pool, page_ids)
    except Exception:
        return []
    return targets if targets or page_ids else _primary_target(bridge)

"""Pool discovery must preserve unavailable workers as unknown, not drop them."""
from __future__ import annotations

import threading
from types import SimpleNamespace

from app.ui.panels.watcher_captcha import get_watcher_targets


class Pool:
    def __init__(self, targets):
        self._lock = threading.RLock()
        self._pages = {tab_id: SimpleNamespace(label=label)
                       for tab_id, label, _, _ in targets}
        self._controllers = {tab_id: ctrl for tab_id, _, _, ctrl in targets}
        self._clients = {tab_id: client for tab_id, _, client, _ in targets}

    def get_clients(self, tab_id):
        return self._clients[tab_id], self._controllers[tab_id]

    def get_page(self, tab_id):
        return self._pages[tab_id]


def test_watcher_targets_include_disconnected_checked_pool_workers():
    connected = SimpleNamespace(is_connected=True)
    disconnected = SimpleNamespace(is_connected=False)
    first_ctrl, second_ctrl = object(), object()
    pool = Pool([("A", "alice_0001", connected, first_ctrl),
                 ("B", "bob_0002", disconnected, second_ctrl)])
    bridge = SimpleNamespace(_page_pool=pool, cdp=None)

    targets = get_watcher_targets(bridge)

    assert [(target.tab_id, target.label, target.cdp) for target in targets] == [
        ("A", "alice_0001", first_ctrl), ("B", "bob_0002", second_ctrl)]


def test_missing_page_client_still_has_a_named_pool_target():
    pool = Pool([("A", "alice_0001", None, None)])
    bridge = SimpleNamespace(_page_pool=pool, cdp=None)

    targets = get_watcher_targets(bridge)

    assert len(targets) == 1 and targets[0].tab_id == "A"
    assert targets[0].label == "alice_0001" and targets[0].cdp is None

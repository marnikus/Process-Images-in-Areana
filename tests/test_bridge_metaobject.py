"""Bridge metaobject registration (W1.6 regression guard).

The panel split moved @Slot methods onto plain-Python mixins. PySide6
registers mixin slots into the QObject metaobject — this test fails if
that ever breaks (a lost slot means QWebChannel silently drops the call,
the exact regression tests/test_bridge_slots.py was written for).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge

# Slots the web UI calls most (Run button, tabs, connectivity).
REPRESENTATIVE_SLOTS = (
    "start_run", "pause_run", "stop_after_current", "cancel_current",
    "get_tabs", "connect_tab", "auto_connect_scan", "get_arena_state",
    "save_settings", "undo", "redo", "get_action_blocks",
)


@pytest.mark.unit
def test_mixin_slots_registered_in_metaobject(tmp_path, qapp):
    bridge = Bridge(ConfigManager(str(tmp_path / "cfg")), tmp_path / "s.json")
    mo = bridge.metaObject()
    registered = set()
    for i in range(mo.methodCount()):
        raw = mo.method(i).name()  # QByteArray/bytes/str depending on build
        try:
            registered.add(bytes(raw).decode("utf-8", "replace"))
        except Exception:
            registered.add(str(raw))
    missing = [name for name in REPRESENTATIVE_SLOTS if name not in registered]
    assert not missing, f"slots lost from metaobject (QWebChannel dead): {missing}"


@pytest.mark.unit
def test_bridge_facade_stays_slim():
    src = Path("app/ui/bridge.py").read_text(encoding="utf-8")
    assert len(src.splitlines()) <= 300, "bridge.py facade must stay <=300 LOC"

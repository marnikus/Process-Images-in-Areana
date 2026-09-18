"""Boot-restore slots (2026-09-18 grid-restore-push).

request_grid_restore / request_window_states_restore must (a) return the saved
payload and (b) emit it as a signal — the proven delivery path that survives a
lost invokeMethod response (which is what left the grid silently on default).

Runs with or without working Qt: where PySide6 QtWidgets cannot load (headless
sandboxes without GL), bridge.py's fake Signal/Slot stubs are active and only
return values are asserted; where real Qt is loaded, the signal emit too.
Docs: docs/archive/2026-09-18-grid-restore-push/design.md
"""

import json
from pathlib import Path

import pytest

from app.core.layout_service import default_payload
from app.persistence.config_manager import ConfigManager
import app.ui.bridge as bridge_mod
from app.ui.bridge import Bridge


def _make_bridge(tmp_path: Path) -> Bridge:
    cfg = ConfigManager(config_dir=str(tmp_path / "config"))
    return Bridge(cfg, tmp_path / "app_state.json")


def _uses_real_qt() -> bool:
    """Real Qt signals? QtWidgets may fail to import headless → fake stubs."""
    return "PySide6" in getattr(bridge_mod.QObject, "__module__", "")


@pytest.mark.unit
def test_request_grid_restore_pushes_saved_layout(tmp_path):
    bridge = _make_bridge(tmp_path)
    saved = default_payload()
    assert bridge.save_grid_layout(saved) is True
    if _uses_real_qt():
        emitted = []
        bridge.grid_layout_restored.connect(lambda v: emitted.append(v))
    payload = bridge.request_grid_restore()
    assert payload == bridge.get_grid_layout()  # canonicalized, stable
    assert payload
    if _uses_real_qt():
        assert emitted == [payload]  # same payload rides the signal


@pytest.mark.unit
def test_request_grid_restore_empty_when_nothing_saved(tmp_path):
    bridge = _make_bridge(tmp_path)
    assert bridge.get_grid_layout() == ""
    if _uses_real_qt():
        emitted = []
        bridge.grid_layout_restored.connect(lambda v: emitted.append(v))
    assert bridge.request_grid_restore() == ""
    if _uses_real_qt():
        assert emitted == []  # nothing to push — never emit empty


@pytest.mark.unit
def test_request_window_states_restore(tmp_path):
    bridge = _make_bridge(tmp_path)
    raw = bridge.request_window_states_restore()
    data = json.loads(raw)
    assert set(data.keys()) == {"closed", "minimized"}
    if _uses_real_qt():
        emitted = []
        bridge.window_states_restored.connect(lambda v: emitted.append(v))
        assert bridge.request_window_states_restore() == raw
        assert emitted == [raw]


@pytest.mark.unit
def test_saved_grid_survives_roundtrip_through_request(tmp_path):
    """A layout saved via the slot must come back unchanged across a restart."""
    bridge = _make_bridge(tmp_path)
    assert bridge.save_grid_layout(default_payload()) is True
    payload = bridge.request_grid_restore()  # canonical form of the saved layout
    # fresh bridge on the same config dir = a restart
    bridge2 = _make_bridge(tmp_path)
    assert bridge2.request_grid_restore() == payload

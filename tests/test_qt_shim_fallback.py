"""Qt shim fallback coverage (W1.6).

Every panel module must stay importable when PySide6 is unavailable
(headless CI, no libGL). The QtCore/QtWidgets fallback lines are otherwise
dead code in the sandbox (real QtCore loads) — this test executes them for
every panel + the bridge facade and restores the real modules afterwards.
"""
from __future__ import annotations

import importlib
import sys

import pytest

PANEL_MODULES = [
    "app.ui.panels._bridge_helpers",
    "app.ui.panels.core_panel",
    "app.ui.panels.arena_state_panel",
    "app.ui.panels.action_status_panel",
    "app.ui.panels.blocks_panel",
    "app.ui.panels.undo_panel",
    "app.ui.panels.grid_layout_panel",
    "app.ui.panels.window_preset_panel",
    "app.ui.panels.thumb_panel",
    "app.ui.panels.url_panel",
    "app.ui.panels.folder_panel",
    "app.ui.panels.queue_panel",
    "app.ui.panels.folder_ai_panel",
    "app.ui.panels.settings_panel",
    "app.ui.panels.presets_panel",
    "app.ui.panels.run_panel",
    "app.ui.panels.watcher_panel",
    "app.ui.panels.pool_panel",
    "app.ui.panels.captcha_panel",
    "app.ui.panels.cdp_panel",
    "app.ui.panels.highlight_panel",
    "app.ui.bridge",
]


@pytest.mark.unit
def test_panels_import_without_qt():
    """Reload every panel with PySide6 blocked -> shim path runs + is sane."""
    saved = {k: v for k, v in sys.modules.items()
             if k == "PySide6" or k.startswith("PySide6.")}
    # module objects of everything we reload, to restore exact identity
    reloaded = {}
    try:
        sys.modules["PySide6.QtCore"] = None   # None entry -> ImportError
        sys.modules["PySide6.QtWidgets"] = None
        for name in PANEL_MODULES:
            mod = importlib.import_module(name)
            reloaded[name] = mod
            fresh = importlib.reload(mod)
            assert hasattr(fresh, "QObject"), f"{name} lost QObject (shim)"
            # @Slot shim must be a transparent decorator
            called = []
            fresh.Slot(str)(lambda x: called.append(x))("ping")
            assert called == ["ping"], f"{name} Slot shim not transparent"
            # Signal shim: connect + emit must be safe no-ops
            sig = fresh.Signal(str)
            sig.connect(lambda *a: None)
            sig.emit("x")
    finally:
        sys.modules.update(saved)
        # re-reload with real Qt so later tests see the genuine modules
        for name in reloaded:
            importlib.reload(sys.modules[name])


@pytest.mark.unit
def test_shim_signal_is_noop():
    """Shim Signal() object tolerates emit/connect without Qt."""
    saved = {k: v for k, v in sys.modules.items()
             if k == "PySide6" or k.startswith("PySide6.")}
    try:
        sys.modules["PySide6.QtCore"] = None
        sys.modules["PySide6.QtWidgets"] = None
        helpers = importlib.reload(importlib.import_module("app.ui.panels._bridge_helpers"))
        sig = helpers.Signal(str)
        sig.connect(lambda *a: None)
        sig.emit("x")  # must not raise
    finally:
        sys.modules.update(saved)
        importlib.reload(sys.modules["app.ui.panels._bridge_helpers"])


@pytest.mark.unit
def test_qt_widgets_import_success_arc():
    """The QtWidgets try-import success arc (real libGL environments).

    In the sandbox PySide6.QtWidgets always fails (no libGL), so the
    import-succeeds branch is never taken. A fake module exercises it.
    """
    import types
    saved = {k: v for k, v in sys.modules.items()
             if k == "PySide6" or k.startswith("PySide6.")}
    try:
        fake = types.ModuleType("PySide6.QtWidgets")
        fake.QFileDialog = object()
        sys.modules["PySide6.QtWidgets"] = fake
        for name in PANEL_MODULES:
            mod = importlib.import_module(name)
            fresh = importlib.reload(mod)
            assert fresh.QFileDialog is fake.QFileDialog, f"{name} did not use fake QtWidgets"
    finally:
        sys.modules.update(saved)
        for name in PANEL_MODULES:
            importlib.reload(sys.modules[name])

"""Qt shim fallback coverage (X2 — ported from Area B's W1.6 test).

Every panel module must stay importable when PySide6 is unavailable
(headless CI, no libGL). `app/ui/qt_compat.py` is the single guarded import
site (RULE 18: one shim, not one per panel), so this test blocks PySide6,
reloads qt_compat + every panel + the bridge facade, and asserts the dummy
QObject/Signal/Slot surface is sane. Real modules are restored afterwards.
"""
from __future__ import annotations

import importlib
import sys

import pytest

PANEL_MODULES = [
    "app.ui.panels.app_settings",
    "app.ui.panels.blocks_library",
    "app.ui.panels.blocks_stack",
    "app.ui.panels.browser_tabs",
    "app.ui.panels.cdp_tools",
    "app.ui.panels.layout_state",
    "app.ui.panels.page_pool",
    "app.ui.panels.queue_scan",
    "app.ui.panels.run_control",
    "app.ui.panels.undo_history",
    "app.ui.panels.url_queue",
    "app.ui.panels.watcher_captcha",
    "app.ui.bridge",
    "app.ui.bridge_context",
    "app.ui.qt_compat",
]


def _block_qt():
    """Snapshot the PySide6 modules and make the next import fail."""
    saved = {k: v for k, v in sys.modules.items()
             if k == "PySide6" or k.startswith("PySide6.")}
    sys.modules["PySide6.QtCore"] = None   # None entry -> ImportError
    sys.modules["PySide6.QtWidgets"] = None
    return saved


@pytest.mark.unit
def test_panels_import_without_qt():
    """Reload every panel with PySide6 blocked -> shim path runs + is sane."""
    saved = _block_qt()
    reloaded = {}
    try:
        for name in PANEL_MODULES:
            mod = importlib.import_module(name)
            reloaded[name] = mod
            fresh = importlib.reload(mod)
            assert hasattr(fresh, "QObject") or "qt_compat" not in name, \
                f"{name} lost QObject (shim)"
            if sys.modules["app.ui.qt_compat"] is None:
                continue
            shim = importlib.reload(sys.modules["app.ui.qt_compat"])
            called = []
            shim.Slot(str)(lambda x: called.append(x))("ping")
            assert called == ["ping"], "Slot shim not transparent"
            sig = shim.Signal(str)
            sig.connect(lambda *a: None)
            sig.emit("x")
    finally:
        sys.modules.update(saved)
        for name in reloaded:
            importlib.reload(sys.modules[name])


@pytest.mark.unit
def test_shim_signal_is_noop():
    """Shim Signal() object tolerates emit/connect without Qt."""
    saved = _block_qt()
    try:
        shim = importlib.reload(importlib.import_module("app.ui.qt_compat"))
        sig = shim.Signal(str)
        sig.connect(lambda *a: None)
        sig.emit("x")  # must not raise
    finally:
        sys.modules.update(saved)
        importlib.reload(sys.modules["app.ui.qt_compat"])


@pytest.mark.unit
def test_qt_widgets_import_success_arc():
    """The QtWidgets try-import success arc (real libGL environments).

    In this sandbox PySide6.QtWidgets always fails (no libGL), so the
    import-succeeds branch is never taken. A fake module exercises it on the
    single shim module; prior tests in this file may have left the blocked
    sentinels behind, so those are dropped first.
    """
    import types
    for sentinel in ("PySide6.QtCore", "PySide6.QtWidgets"):
        if sys.modules.get(sentinel) is None:
            sys.modules.pop(sentinel, None)
    saved = sys.modules.get("PySide6.QtWidgets", "absent")
    try:
        fake = types.ModuleType("PySide6.QtWidgets")
        fake.QFileDialog = object()
        sys.modules["PySide6.QtWidgets"] = fake
        fresh = importlib.reload(importlib.import_module("app.ui.qt_compat"))
        assert fresh.QFileDialog is fake.QFileDialog, \
            "qt_compat did not take QFileDialog from PySide6.QtWidgets"
        assert fresh.QFileDialog is not None
    finally:
        if saved == "absent":
            sys.modules.pop("PySide6.QtWidgets", None)
        else:
            sys.modules["PySide6.QtWidgets"] = saved
        importlib.reload(importlib.import_module("app.ui.qt_compat"))

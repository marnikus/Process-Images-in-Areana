"""qt_compat shim tests (R10.12): clipboard centralization, headless behavior."""

import importlib.util

import pytest

from app.ui import qt_compat


needs_no_qt = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is not None,
    reason="headless-only: PySide6 present",
)


@needs_no_qt
def test_get_clipboard_headless_is_none():
    assert qt_compat.get_clipboard() is None


@needs_no_qt
def test_clipboard_copy_headless_returns_false_none():
    assert qt_compat.clipboard_copy("hello") == (False, None)


def test_shim_exports_clipboard_helpers():
    assert "get_clipboard" in qt_compat.__all__
    assert "clipboard_copy" in qt_compat.__all__


@needs_no_qt
def test_dummy_signal_wire_smoke():
    sig = qt_compat.Signal()
    sig.connect(lambda: None)
    sig.emit("x")
    obj = qt_compat.QObject()
    assert obj is not None and qt_compat.QFileDialog is None

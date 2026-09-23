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


needs_qt = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="needs PySide6 installed",
)


def _qt_app():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return None
    return QApplication.instance()


@needs_qt
def test_get_clipboard_none_without_app():
    if _qt_app() is not None:
        pytest.skip("a QApplication already exists in this run")
    assert qt_compat.get_clipboard() is None


@needs_qt
def test_clipboard_copy_without_app_returns_false_none():
    if _qt_app() is not None:
        pytest.skip("a QApplication already exists in this run")
    assert qt_compat.clipboard_copy("hello") == (False, None)


@needs_qt
def test_clipboard_paths_with_offscreen_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as e:
        pytest.skip(f"PySide6 QtWidgets unavailable here: {e}")
    app = _qt_app() or QApplication([])
    assert qt_compat.get_clipboard() is app.clipboard()
    ok, err = qt_compat.clipboard_copy("arena-clipboard-check")
    assert ok is True and err is None

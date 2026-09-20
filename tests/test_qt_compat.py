"""qt_compat shim tests (R10.12): clipboard centralization, headless behavior."""

import importlib.util
import sys

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


# --- S0 (2026-09-21): the clipboard helpers were only covered where PySide6 is
# absent (headless tests above) or fully loadable (real QApplication). With
# PySide6 installed but QtWidgets unloadable (no libGL) neither arc ran and the
# file fell below its coverage floor. Fake Qt modules exercise every arc in
# every environment; sys.modules is restored by monkeypatch.

class _FakeClipboard:
    def __init__(self, fail_modes=()):
        self.fail_modes = set(fail_modes)
        self.calls = []

    def setText(self, text, mode=None):
        self.calls.append((text, mode))
        if mode in self.fail_modes:
            raise RuntimeError(f"mode {mode} unavailable")


def _fake_qt(monkeypatch, *, widgets_app=None, gui_app=None):
    """Install fake PySide6.QtWidgets/QtGui whose *Application.instance() return the given apps."""
    import types

    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    def app_class(instance):
        return type("App", (), {"instance": staticmethod(lambda: instance)})

    clipboard_enum = type("QClipboard", (), {"Clipboard": "clip", "Selection": "sel"})
    module("PySide6.QtWidgets", QApplication=app_class(widgets_app))
    module("PySide6.QtGui", QGuiApplication=app_class(gui_app), QClipboard=clipboard_enum)


def _app_with(clipboard):
    return type("Host", (), {"clipboard": lambda self: clipboard})()


def test_get_clipboard_prefers_qapplication(monkeypatch):
    primary, fallback = _FakeClipboard(), _FakeClipboard()
    _fake_qt(monkeypatch, widgets_app=_app_with(primary), gui_app=_app_with(fallback))
    assert qt_compat.get_clipboard() is primary


def test_get_clipboard_falls_back_to_gui_application(monkeypatch):
    fallback = _FakeClipboard()
    _fake_qt(monkeypatch, widgets_app=None, gui_app=_app_with(fallback))
    assert qt_compat.get_clipboard() is fallback


def test_get_clipboard_none_when_no_application(monkeypatch):
    _fake_qt(monkeypatch, widgets_app=None, gui_app=None)
    assert qt_compat.get_clipboard() is None


def test_clipboard_copy_sets_clipboard_and_selection(monkeypatch):
    clipboard = _FakeClipboard()
    _fake_qt(monkeypatch, widgets_app=_app_with(clipboard))
    assert qt_compat.clipboard_copy("hello") == (True, None)
    assert clipboard.calls == [("hello", "clip"), ("hello", "sel")]


def test_clipboard_copy_tolerates_missing_selection(monkeypatch):
    clipboard = _FakeClipboard(fail_modes={"sel"})
    _fake_qt(monkeypatch, widgets_app=_app_with(clipboard))
    assert qt_compat.clipboard_copy("hello") == (True, None)


def test_clipboard_copy_reports_qt_failure(monkeypatch):
    clipboard = _FakeClipboard(fail_modes={"clip"})
    _fake_qt(monkeypatch, widgets_app=_app_with(clipboard))
    ok, warn = qt_compat.clipboard_copy("hello")
    assert ok is False
    assert warn.startswith("Qt clipboard failed") and "trying subprocess" in warn

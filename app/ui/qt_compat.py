"""Qt compatibility shim — the ONLY Qt import site for ui/ (Area A5).

Panels and bridge import QObject/Signal/Slot/QFileDialog from here so the
headless fallback (ImportError -> dummies) exists exactly once. Services
(core/browser/services/ui-services) must never import this module.
"""

try:
    from PySide6.QtCore import QObject, Signal, Slot
    from PySide6.QtWidgets import QFileDialog
except ImportError:  # headless/test: duck-type dummies
    class QObject:
        def __init__(self, *_a, **_kw):
            pass

    def Signal(*_a, **_kw):
        class _Sig:
            def emit(self, *_a, **_kw):
                pass

            def connect(self, *_a, **_kw):
                pass

        return _Sig()

    def Slot(*_a, **_kw):
        def deco(fn):
            return fn

        return deco

    QFileDialog = None


def get_clipboard():
    """Qt clipboard via QApplication, else QGuiApplication (None when absent)."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            return app.clipboard()
    except Exception:
        pass
    try:
        from PySide6.QtGui import QGuiApplication
        app2 = QGuiApplication.instance()
        if app2 is not None:
            return app2.clipboard()
    except Exception:
        pass
    return None


def clipboard_copy(text: str):
    """Qt clipboard attempt; (True, None) / (False, warn-or-None)."""
    clipboard = get_clipboard()
    if clipboard is None:
        return False, None
    try:
        from PySide6.QtGui import QClipboard
        clipboard.setText(text, mode=QClipboard.Clipboard)
        try:
            clipboard.setText(text, mode=QClipboard.Selection)
        except Exception:
            pass
        return True, None
    except Exception as e_qt:
        return False, f"Qt clipboard failed {e_qt}, trying subprocess"


__all__ = ["QObject", "Signal", "Slot", "QFileDialog",
           "get_clipboard", "clipboard_copy"]

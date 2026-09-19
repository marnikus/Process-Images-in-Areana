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
        def __init__(self, *a, **kw):
            pass

    def Signal(*a, **kw):
        class _Sig:
            def emit(self, *a, **kw):
                pass

            def connect(self, *a, **kw):
                pass

        return _Sig()

    def Slot(*a, **kw):
        def deco(fn):
            return fn

        return deco

    QFileDialog = None


__all__ = ["QObject", "Signal", "Slot", "QFileDialog"]

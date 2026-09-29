from __future__ import annotations
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from app.utils.js_console import js_console_line
from app.utils.logging import get_logger

class _ConsolePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, *args):
        level, message, line_number, source_id = args
        where = f"{source_id}:{line_number}" if source_id else f"line {line_number}"
        lvl, line = js_console_line(level, message, where)
        getattr(get_logger(), lvl)(line)

def _build_view(parent) -> QWebEngineView:
    view = QWebEngineView(parent)
    view.setPage(_ConsolePage(view))
    return view

def _is_valid_geometry(saved: dict) -> bool:
    try:
        w = int(saved["width"])
        h = int(saved["height"])
        int(saved["x"])
        int(saved["y"])
        return w > 0 and h > 0
    except (KeyError, TypeError, ValueError, AttributeError):
        return False

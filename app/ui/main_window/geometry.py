from __future__ import annotations
from pathlib import Path

def _restore_window_geometry(window, config_manager, is_valid):
    try:
        saved = config_manager.get_state("window_geometry", None)
        if not isinstance(saved, dict):
            return
        if not is_valid(saved):
            return
        x = int(saved["x"])
        y = int(saved["y"])
        w = int(saved["width"])
        h = int(saved["height"])
        window.setGeometry(x, y, w, h)
    except Exception:
        pass

def _save_window_geometry(window, config_manager) -> None:
    try:
        g = window.geometry()
        config_manager.set_state(window_geometry={"x": int(g.x()), "y": int(g.y()), "width": int(g.width()), "height": int(g.height())})
    except Exception:
        pass

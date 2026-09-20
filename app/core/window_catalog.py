"""Window catalog — the ONE ordered table of dockable windows (S8, D-20/D-21, I-51).

`WINDOWS` is the source of truth; ids, titles and the default tree are
derived from it. `js/sash-core/constants.js` mirrors this list exactly
(pinned by `tests/test_window_catalog.py`); `index.html` must mount every id
as `data-window="<id>"` and nothing else (the L-5 orphan `page_pool` panel
used to be discarded by `SashGrid.render()`). Adding a window is one row
here, one same-line append in the three JS registries, and its markup.
`layout_service` re-exports these names for its existing importers.
"""
# ideal-size: ~65 lines reason=a table plus its derived views; the parsing/migration logic
# stays in layout_service so the window list has exactly one owner (RULE 10 / 18.2).

from __future__ import annotations

WINDOWS = [
    {"id": "url_list", "title": "URL List"},
    {"id": "folder", "title": "Folder Picker"},
    {"id": "queue", "title": "Image Queue"},
    {"id": "prompt", "title": "Prompt Editor"},
    {"id": "run", "title": "Run Controls"},
    {"id": "progress", "title": "Progress"},
    {"id": "watcher", "title": "Watcher — Generation & Captcha"},
    {"id": "log", "title": "Activity Log"},
    {"id": "settings", "title": "Settings"},
    {"id": "captcha", "title": "Captcha — Solver (2Captcha / CapMonster)"},
    {"id": "recordings", "title": "Recordings — Captcha Sessions"},
    {"id": "browser", "title": "Browser Preview"},
    {"id": "action_blocks", "title": "Action Blocks — Stacking Jobs"},
    {"id": "block_config", "title": "Block Config — Security Check"},
    {"id": "arena_presets", "title": "Arena Presets"},
    {"id": "live_debug", "title": "Live Worker & Queue Debug"},
]
WINDOW_IDS = [w["id"] for w in WINDOWS]
WINDOW_TITLES = {w["id"]: w["title"] for w in WINDOWS}
# Windows this app renamed. A stored layout that still uses one keeps its
# position + sizes under the new id (never rejected, never default-substituted).
LEGACY_WINDOW_IDS = {"captcha_records": "recordings"}
GRID_VERSION = 6   # 5 → 6: the live_debug window (a stored v5 layout migrates, it is never rejected)


def _leaf(i):
    return {"t": "leaf", "id": i}


def _split(d, kids, sizes):
    return {"t": "split", "dir": d, "children": kids, "sizes": sizes}


def default_grid_tree() -> dict:
    """The factory layout: every registered window exactly once, sizes summing to 100."""
    return _split("col", [
        _split("row", [
            _split("col", [_leaf("url_list"), _leaf("folder")], [55, 45]),
            _split("col", [_leaf("prompt"), _leaf("run"), _leaf("settings"),
                           _leaf("captcha"), _leaf("recordings")], [35, 20, 20, 12, 13]),
        ], [60, 40]),
        _split("row", [
            _leaf("queue"),
            _split("col", [_leaf("action_blocks"), _leaf("block_config")], [55, 45]),
            _split("col", [_leaf("browser"), _leaf("arena_presets"), _leaf("progress"),
                           _leaf("watcher"), _leaf("live_debug")], [24, 20, 16, 20, 20]),
        ], [45, 35, 20]),
        _leaf("log"),
    ], [38, 40, 22])

"""The ONE ordered window table (S8, I-51) — Python owns it, JS mirrors it.

`WINDOW_IDS` / `WINDOW_TITLES` are derived, never hand-written (L-8: two
hand-kept lists drifted on `recordings`' position). Adding a window is one
row here + the same-line appends in `sash-core/constants.js`,
`sash-grid-windows/store.js`, `arena-app.js` `_PANEL_INITS`, and the panel
markup in `index.html` (`tests/test_window_catalog.py` locks all four).
"""

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
GRID_VERSION = 6  # 5 → 6 (S8): the 16th window; v5 layouts migrate (extra leaf), never rejected


def default_grid_tree() -> dict:
    def leaf(i):
        return {"t": "leaf", "id": i}

    def split(d, kids, sizes):
        return {"t": "split", "dir": d, "children": kids, "sizes": sizes}

    return split("col", [
        split("row", [
            split("col", [leaf("url_list"), leaf("folder")], [55, 45]),
            split("col", [leaf("prompt"), leaf("run"), leaf("settings"),
                          leaf("captcha"), leaf("recordings")], [35, 20, 20, 12, 13]),
        ], [60, 40]),
        split("row", [
            leaf("queue"),
            split("col", [leaf("action_blocks"), leaf("block_config")], [55, 45]),
            split("col", [leaf("browser"), leaf("arena_presets"), leaf("progress"),
                          leaf("watcher"), leaf("live_debug")], [25, 20, 15, 20, 20]),
        ], [45, 35, 20]),
        leaf("log"),
    ], [38, 40, 22])

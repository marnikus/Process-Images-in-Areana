"""Window catalog — the one ordered table for sash-grid windows (S8).

Owns the 16-window set, ids ≡ order ≡ titles, plus GRID_VERSION and
LEGACY_WINDOW_IDS. layout_service re-exports this module (shim).
No imports from UI, browser or services.
ideal-size: pure-data leaf under 150 lines; keep the registry and default together.
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
LEGACY_WINDOW_IDS = {"captcha_records": "recordings"}
GRID_VERSION = 6


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
            split("col", [leaf("browser"), leaf("arena_presets"),
                          leaf("progress"), leaf("watcher"), leaf("live_debug")], [24, 20, 18, 20, 18]),
        ], [45, 35, 20]),
        leaf("log"),
    ], [38, 40, 22])

"""Slot-registration guard — every JS-called bridge method must keep @Slot.

Regression: an edit once inserted helpers between @Slot and start_run,
silently killing the Run button (QWebChannel drops unknown calls with
no log). AST-based, no Qt needed.
"""

from pathlib import Path

import pytest

UI = Path(__file__).parent.parent / "app" / "ui"
BRIDGE = UI / "bridge.py"
PANELS = UI / "panels"

# Methods the web UI calls that must stay slots (extend with new slots).
REQUIRED_SLOTS = (
    "start_run", "pause_run", "resume_run", "stop_after_current",
    "cancel_current", "reset_page_cooldown", "set_page_cooldown",
    "auto_connect_scan", "popup_url_tabs", "get_tabs", "connect_tab",
    "add_url", "remove_url", "ensure_primary_connected", "stop_tab_job",
    "drop_ai_suffix", "keep_only_ai_files",
    "get_stack_presets", "save_stack_preset", "delete_stack_preset", "export_action_blocks",
    "set_captcha_settings", "get_captcha_status", "get_captcha_stats",
    "restore_default_blocks",
    "watcher_start", "watcher_stop", "watcher_status",
    "set_captcha_api_key", "get_captcha_api_key", "captcha_balance", "set_captcha_provider",
    "get_recordings_list", "get_recording_detail", "get_recording_snapshot",
    "get_recording_diff", "set_recording_label", "delete_recording",
    "set_recording_settings", "get_recording_settings",
    "get_job_history", "clear_job_history",
    "get_firefox_auto_config", "save_firefox_auto_config",
    "run_firefox_auto_test", "stop_firefox_auto_test",
    "show_firefox_profiles",
)

# Private helpers that must never capture a @Slot by accident.
NEVER_SLOTS = (
    "_settle_stuck_primary", "_finish_primary_tab", "_reset_stuck_page",
    "_do_run_batch", "_do_auto_connect_scan", "_do_popup_url_tabs",
    "_settle_captcha_at", "_captcha_service", "_recording_service",
)


def _slot_names(path: Path) -> set:
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(func, ast.Name) and func.id == "Slot":
                names.add(node.name)
    return names


@pytest.mark.unit
def test_required_slots_registered():
    names = _slot_names(BRIDGE)
    if PANELS.exists():
        for panel in PANELS.glob("*.py"):
            names |= _slot_names(panel)
    missing = [s for s in REQUIRED_SLOTS if s not in names]
    assert not missing, f"lost @Slot decorator: {missing}"


@pytest.mark.unit
def test_helpers_never_slots():
    paths = [BRIDGE] + (list(PANELS.glob("*.py")) if PANELS.exists() else [])
    for path in paths:
        names = _slot_names(path)
        stolen = [s for s in NEVER_SLOTS if s in names]
        assert not stolen, f"helper captured @Slot in {path.name}: {stolen}"


# ── F5 frozen surface + F6 packing (R12/A7) ──

# Contract design §1 item 1: the 119 JS slot names, frozen. Any add/remove
# must update this set deliberately (JS contract review).
FROZEN_SLOTS = frozenset({
    'delete_recording',
    'get_recording_detail',
    'get_recording_diff',
    'get_recording_settings',
    'get_recording_snapshot',
    'get_recordings_list',
    'set_recording_label',
    'set_recording_settings',
    'add_action_block',
    'add_url',
    'add_url_preset',
    'auto_connect_scan',
    'bulk_select',
    'cancel_current',
    'cdp_attach_image_test',
    'cdp_insert_prompt_test',
    'cdp_test_full_flow',
    'check_watcher_now',
    'clear_highlights',
    'clear_images',
    'clear_job_history',
    'clear_page_pool',
    'clear_queue',
    'clear_watcher_overlay',
    'connect_page_pool',
    'connect_tab',
    'copy_path_to_clipboard',
    'delete_action_block',
    'delete_arena_preset',
    'delete_custom_block',
    'delete_prompt_preset',
    'delete_stack_preset',
    'delete_window_preset',
    'diagnose_chrome',
    'disconnect_page_pool',
    'drop_ai_suffix',
    'edit_url',
    'ensure_primary_connected',
    'export_action_blocks',
    'export_custom_block',
    'export_preset',
    'export_window_preset',
    'find_tab_by_url',
    'get_action_blocks',
    'get_app_state',
    'get_arena_state',
    'get_builtin_blocks',
    'get_captcha_stats',
    'get_captcha_status',
    'get_cdp_config',
    'get_chrome_launch_command',
    'get_cooldown_config',
    'get_custom_blocks',
    'get_grid_layout',
    'get_image_thumbnail',
    'get_job_history',
    'get_page_pool_status',
    'get_stack_history',
    'get_stack_presets',
    'get_tabs',
    'get_undo_history',
    'get_url_presets',
    'get_watcher_config',
    'get_watcher_state',
    'get_window_states',
    'highlight_image',
    'highlight_selector',
    'import_preset',
    'import_window_preset',
    'keep_only_ai_files',
    'list_arena_presets',
    'list_prompt_presets',
    'list_window_presets',
    'load_arena_preset',
    'load_prompt_preset',
    'load_window_preset',
    'pause_run',
    'pick_folder',
    'popup_url_tabs',
    'push_global_history',
    'push_stack_history',
    'redo',
    'redo_grid_layout',
    'redo_stack',
    'refresh_users',
    'remove_url',
    'remove_url_preset',
    'reset_action_blocks',
    'reset_all',
    'reset_grid_layout',
    'reset_image',
    'reset_page_cooldown',
    'resume_run',
    'retry_failed',
    'retry_image',
    'reveal_in_explorer',
    'save_action_blocks',
    'save_arena_preset',
    'save_custom_block',
    'save_grid_layout',
    'save_prompt_preset',
    'save_settings',
    'save_stack_history',
    'save_stack_preset',
    'save_window_preset',
    'save_window_states',
    'scan_folder',
    'scan_folder_new_batch',
    'set_captcha_settings',
    'set_cdp_config',
    'set_cooldown_config',
    'set_folder_path',
    'set_image_selected',
    'set_last_url_preset',
    'set_page_cooldown',
    'set_prompt',
    'set_theme',
    'set_watcher_config',
    'show_window_preset_in_folder',
    'start_run',
    'start_watcher',
    'stop_after_current',
    'stop_tab_job',
    'stop_watcher',
    'test_url',
    'toggle_url',
    'undo',
    'undo_grid_layout',
    'undo_stack',
    # 2026-10-02 bugfix release
    'restore_default_blocks',
    # 2026-10-02 Captcha Watcher isolation (panels/watcher_solver.py)
    'watcher_start',
    'watcher_stop',
    'watcher_status',
    'set_captcha_api_key',
    'set_captcha_provider',
    'get_captcha_api_key',
    'captcha_balance',
    # 2026-09-22 I-63: the "Firefox auto with Extension" window (panels/firefox_auto.py)
    'get_firefox_auto_config',
    'save_firefox_auto_config',
    'run_firefox_auto_test',
    'stop_firefox_auto_test',
    'show_firefox_profiles',  # 2026-09-24: profile listing for the selection filter
})


# Design packing table (implementation-area-a.md): per-panel slot counts.
EXPECTED_PACKING = {
    'app_settings': 10,
    'blocks_library': 9,
    'blocks_stack': 11,
    'browser_tabs': 7,
    'cdp_tools': 9,
    'layout_state': 14,
    'page_pool': 9,
    'queue_scan': 10,
    'queue_scan_folder': 2,
    'recording_sessions': 8,
    'run_control': 10,
    'undo_history': 10,
    'url_queue': 9,
    'watcher_captcha': 10,
    'watcher_solver': 7,
    'job_history': 2,
    'firefox_auto': 5,
}


def _panel_slot_counts() -> dict:
    counts = {}
    for panel in PANELS.glob("*.py"):
        if panel.name == "__init__.py":
            continue
        counts[panel.stem] = len(_slot_names(panel))
    return counts


def _bridge_direct_methods() -> list:
    import ast
    tree = ast.parse(BRIDGE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Bridge":
            return [n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    raise AssertionError("Bridge class not found")


@pytest.mark.unit
def test_frozen_slot_surface_exact():
    names = _slot_names(BRIDGE)
    for panel in PANELS.glob("*.py"):
        names |= _slot_names(panel)
    assert names == FROZEN_SLOTS, (f"slot surface drift: lost={sorted(FROZEN_SLOTS - names)}, "
                                   f"added={sorted(names - FROZEN_SLOTS)}")


@pytest.mark.unit
def test_panel_packing():
    counts = _panel_slot_counts()
    assert counts == EXPECTED_PACKING, f"packing drift: {counts}"
    # 127 + 6 Captcha Watcher + restore_default_blocks (2026-10-02) + set_captcha_provider (B10, 2026-10-06)
    # +2 job_history slots +5 firefox_auto slots (I-63, 2026-09-22; +show_firefox_profiles 2026-09-24)
    assert sum(counts.values()) == 142


@pytest.mark.unit
def test_bridge_direct_methods_capped():
    methods = _bridge_direct_methods()
    assert len(methods) <= 10, f"Bridge grew past 10 direct methods: {methods}"
    assert not (_slot_names(BRIDGE) & FROZEN_SLOTS), "slots must live in panels, not Bridge"

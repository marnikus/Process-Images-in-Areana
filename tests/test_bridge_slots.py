"""Slot-registration guard — every JS-called bridge method must keep @Slot.

Regression: an edit once inserted helpers between @Slot and start_run,
silently killing the Run button (QWebChannel drops unknown calls with
no log). AST-based, no Qt needed.
"""

from pathlib import Path

import pytest

BRIDGE = Path(__file__).parent.parent / "app" / "ui" / "bridge.py"
RECORDINGS_ADAPTER = (Path(__file__).parent.parent / "app" / "ui" / "services"
                      / "captcha_recordings_bridge.py")

# Methods the web UI calls that must stay slots (extend with new slots).
REQUIRED_SLOTS = (
    "start_run", "pause_run", "resume_run", "stop_after_current",
    "cancel_current", "reset_page_cooldown", "set_page_cooldown",
    "auto_connect_scan", "popup_url_tabs", "get_tabs", "connect_tab",
    "add_url", "remove_url", "ensure_primary_connected", "stop_tab_job",
    "drop_ai_suffix", "keep_only_ai_files",
    "get_stack_presets", "save_stack_preset", "delete_stack_preset", "export_action_blocks",
    "set_captcha_settings", "get_captcha_status", "get_captcha_stats",
)

# The Recordings window has its own QWebChannel adapter; every method there is
# called from JS and must keep @Slot or the panel silently stops updating.
REQUIRED_ADAPTER_SLOTS = (
    "list_sessions", "list_all_sessions", "delete_session", "delete_all_sessions",
    "undo_delete", "set_label", "set_labels", "get_session", "compare_sessions",
    "open_folder",
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
    missing = [s for s in REQUIRED_SLOTS if s not in names]
    assert not missing, f"lost @Slot decorator: {missing}"


@pytest.mark.unit
def test_recordings_adapter_slots_registered():
    names = _slot_names(RECORDINGS_ADAPTER)
    missing = [s for s in REQUIRED_ADAPTER_SLOTS if s not in names]
    assert not missing, f"recordings adapter lost @Slot decorator: {missing}"


@pytest.mark.unit
def test_helpers_never_slots():
    names = _slot_names(BRIDGE)
    stolen = [s for s in NEVER_SLOTS if s in names]
    assert not stolen, f"helper captured @Slot: {stolen}"

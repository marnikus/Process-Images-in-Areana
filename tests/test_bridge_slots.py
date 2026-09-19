"""Slot-registration guard — every JS-called bridge method must keep @Slot.

Regression: an edit once inserted helpers between @Slot and start_run,
silently killing the Run button (QWebChannel drops unknown calls with
no log). AST-based, no Qt needed.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
BRIDGE = REPO / "app" / "ui" / "bridge.py"
# W1.6: @Slot methods live on panel mixins; every file that can carry
# slots is scanned so a move can never silently drop one.
SLOT_FILES = sorted((REPO / "app" / "ui" / "panels").glob("*_panel.py")) + [BRIDGE]

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

# Private helpers that must never capture a @Slot by accident.
NEVER_SLOTS = (
    "_settle_stuck_primary", "_finish_primary_tab", "_reset_stuck_page",
    "_do_run_batch", "_do_auto_connect_scan", "_do_popup_url_tabs",
    "_settle_captcha_at", "_captcha_service",
)


def _slot_names(paths) -> set:
    """Slot names across all files that may carry @Slot (W1.6 panels)."""
    names = set()
    for path in paths:
        names |= _slot_names_one(path)
    return names


def _slot_names_one(path: Path) -> set:
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
    names = _slot_names(SLOT_FILES)
    missing = [s for s in REQUIRED_SLOTS if s not in names]
    assert not missing, f"lost @Slot decorator: {missing}"


@pytest.mark.unit
def test_helpers_never_slots():
    names = _slot_names(SLOT_FILES)
    stolen = [s for s in NEVER_SLOTS if s in names]
    assert not stolen, f"helper captured @Slot: {stolen}"

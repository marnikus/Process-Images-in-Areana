"""Probe selector lists — generated from site_adapter (RULE 21 single source).

Every JS probe payload in cdp_arena.py / output_probes.py / new_chat.py
receives its selectors from here; no selector literal may appear in a
probe file (enforced by tests/test_probe_selectors.py). Imports:
site_adapter only (same layer).
"""

from __future__ import annotations

from typing import Dict, List

from .site_adapter import get_readiness_requirements, get_selector


def account_email_probe() -> Dict[str, str]:
    """Logged-in account row: sidebar scope + candidate text selectors (D-5)."""
    sel = get_selector("account_email")
    return {"scope": sel.scope or "", "selectors": sel.all_selectors()}


def textarea_selectors() -> List[str]:
    """Composer textarea list for find/insert probes — primary first."""
    return get_selector("prompt_textarea").all_selectors()


def textarea_primary() -> str:
    """Primary composer selector for verify/highlight/page-loaded probes."""
    return get_selector("prompt_textarea").primary


def send_click_selectors() -> List[str]:
    """Send-button click list — enabled-first."""
    return get_selector("send_button").all_selectors()


def send_click_primary() -> str:
    """Enabled-first send selector — visual click / highlight fallback."""
    return get_selector("send_button").primary


def send_presence_selector() -> str:
    """Un-narrowed send selector — state scans and highlights see disabled too."""
    return get_selector("send_button").presence()


def attachment_preview_selectors() -> List[str]:
    """Attachment preview list for the verify-attachment probe."""
    return get_selector("attachment_preview_image").all_selectors()


def output_image_selectors() -> List[str]:
    """Output image list — identical to the live output_probes v4 list."""
    return get_selector("output_image").all_selectors()


def spinner_selector() -> str:
    """Processing spinner selector for generating-state scans."""
    return get_selector("processing_spinner").primary


def readiness_checks() -> List[Dict[str, str]]:
    """Composite readiness checks [{name, sel}] from site_adapter requirements."""
    return [
        {"name": key.split("_")[0], "sel": get_selector(key).presence()}
        for key in get_readiness_requirements()
    ]


def security_dialog_check() -> Dict[str, str]:
    """Open-dialog selector + text marker for the readiness gate."""
    dialog = get_selector("security_dialog")
    return {"sel": dialog.primary, "text": dialog.textCondition}


def model_label_probe() -> Dict[str, str]:
    """Model-row scope + label selector for the Response A/B spinner label."""
    label = get_selector("model_label")
    return {"scope": label.scope, "label": label.primary}


def new_chat_selectors() -> List[str]:
    """New Chat click-candidate selectors — semantic href first."""
    return get_selector("new_chat_button").all_selectors()


def new_chat_primary() -> str:
    """The New Chat link — the Firefox reset XClick target (RULE 21)."""
    return get_selector("new_chat_button").primary


def add_files_primary() -> str:
    """The composer's “Add files” button — the Firefox upload XClick target (RULE 21)."""
    return get_selector("add_files_button").primary


def add_files_menu_item_selectors() -> List[str]:
    """The “Add files” item of the popup the + button opens (it opens the OS dialog)."""
    return get_selector("add_files_menu_item").all_selectors()


def add_files_menu_item_text() -> str:
    """The item's label — preferred when several candidates match."""
    return get_selector("add_files_menu_item").textCondition or ""

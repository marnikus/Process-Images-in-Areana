"""Probe selector lists — generated from site_adapter (RULE 21 single source)."""
from __future__ import annotations

import json
from typing import Dict, List

from .site_adapter import CONVERSATION_PATH_PREFIX, NEW_CHAT_PATH, get_readiness_requirements, get_selector


def account_email_probe() -> Dict[str, str]:
    sel = get_selector("account_email")
    return {"scope": sel.scope or "", "selectors": sel.all_selectors()}

def textarea_selectors() -> List[str]:
    return get_selector("prompt_textarea").all_selectors()

def textarea_primary() -> str:
    return get_selector("prompt_textarea").primary

def send_click_selectors() -> List[str]:
    return get_selector("send_button").all_selectors()

def send_click_primary() -> str:
    return get_selector("send_button").primary

def send_presence_selector() -> str:
    return get_selector("send_button").presence()

def attachment_preview_selectors() -> List[str]:
    return get_selector("attachment_preview_image").all_selectors()

def output_image_selectors() -> List[str]:
    return get_selector("output_image").all_selectors()

def user_message_selector() -> str:
    return ", ".join(get_selector("user_message").all_selectors())

def spinner_selector() -> str:
    return get_selector("processing_spinner").primary

def generating_spinners_js() -> str:
    sel, scope = json.dumps(spinner_selector()), json.dumps(model_label_probe()["scope"])
    return (f"(() => Array.from(document.querySelectorAll({sel}))"
            f".filter((s) => s.offsetParent !== null && !!s.closest({scope})))")

def readiness_checks() -> List[Dict[str, str]]:
    return [
        {"name": key.split("_")[0], "sel": get_selector(key).presence()}
        for key in get_readiness_requirements()
    ]

def security_dialog_check() -> Dict[str, str]:
    dialog = get_selector("security_dialog")
    return {"sel": dialog.primary, "text": dialog.textCondition}

def model_label_probe() -> Dict[str, str]:
    label = get_selector("model_label")
    return {"scope": label.scope, "label": label.primary}

def new_chat_selectors() -> List[str]:
    return get_selector("new_chat_button").all_selectors()

def new_chat_path() -> str:
    return NEW_CHAT_PATH

def conversation_path_prefix() -> str:
    return CONVERSATION_PATH_PREFIX

_STORAGE_HOSTS = ("cloudflarestorage", "messages-prod")

def chat_output_selectors() -> List[str]:
    return [sel for sel in output_image_selectors() if any(h in sel for h in _STORAGE_HOSTS)]

def new_chat_primary() -> str:
    return get_selector("new_chat_button").primary

def add_files_primary() -> str:
    return get_selector("add_files_button").primary

def add_files_menu_item_selectors() -> List[str]:
    return get_selector("add_files_menu_item").all_selectors()

def add_files_menu_item_text() -> str:
    return get_selector("add_files_menu_item").textCondition or ""

def assistant_message_selectors() -> List[str]:
    return get_selector("assistant_message").all_selectors()

def assistant_text_selectors() -> List[str]:
    return get_selector("assistant_text_output").all_selectors()

def text_output_selectors() -> List[str]:
    return assistant_text_selectors()

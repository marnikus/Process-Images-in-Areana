
from __future__ import annotations

from .block_attach import BLOCK_ATTACH_DEFS
from .block_control import BLOCK_CONTROL_DEFS
from .block_custom import BLOCK_CUSTOM_DEFS
from .block_observe import BLOCK_OBSERVE_DEFS
from .block_persist import BLOCK_PERSIST_DEFS
from .block_prompt import BLOCK_PROMPT_DEFS
from .block_security import BLOCK_SECURITY_DEFS
from .block_submit import BLOCK_SUBMIT_DEFS
from .block_visual import BLOCK_VISUAL_DEFS
from .block_wait import BLOCK_WAIT_DEFS
from .keys import RETIRED_KEYS
from .stacks import DEFAULT_STACK_ORDER, DESCRIPTION_STACK_ORDER

BLOCK_DEFINITIONS = {}
for _d in [
    BLOCK_CUSTOM_DEFS,
    BLOCK_OBSERVE_DEFS,
    BLOCK_SECURITY_DEFS,
    BLOCK_VISUAL_DEFS,
    BLOCK_ATTACH_DEFS,
    BLOCK_PROMPT_DEFS,
    BLOCK_SUBMIT_DEFS,
    BLOCK_WAIT_DEFS,
    BLOCK_PERSIST_DEFS,
    BLOCK_CONTROL_DEFS,
]:
    BLOCK_DEFINITIONS.update(_d)

BUILTIN_BLOCKS = []
for _bid, _def in BLOCK_DEFINITIONS.items():
    BUILTIN_BLOCKS.append(
        {
            "block_id": _bid,
            "name": _def.get("name", _bid),
            "icon": _def.get("icon", "extension"),
            "description": _def.get("description", ""),
            "category": _def.get("category", "action"),
            "required": _def.get("required", False),
            "allow_duplicate": _def.get("allow_duplicate", False),
            "defaults": {
                "selector": _def.get("default_selector", ""),
                "label_selector": _def.get("default_label_selector", ""),
                "match_text": _def.get("default_match_text", ""),
                "match_mode": _def.get("default_match_mode", "contains"),
                "click_enabled": _def.get("default_click_enabled", True),
                "click_selector": _def.get("default_click_selector", ""),
                "fallback_selector": _def.get("default_fallback_selector", ""),
                "fallback_text": _def.get("default_fallback_text", ""),
                "highlight_enabled": _def.get("default_highlight_enabled", True),
                "color": _def.get("default_color", "#FF0000"),
                "timeout_ms": _def.get("default_timeout_ms", 10000),
                "pre_delay_ms": _def.get("default_pre_delay_ms", 200),
                "highlight_ms": _def.get("default_highlight_ms", 2000),
                "confirm_pause_ms": _def.get("default_confirm_pause_ms", 700),
                "enabled": _def.get("default_enabled", True),
                **(_def.get("extra_defaults", {})),
            },
            "labels": _def.get("labels", {}),
        }
    )

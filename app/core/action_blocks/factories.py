from __future__ import annotations

from typing import List
import uuid

from .definitions import BLOCK_DEFINITIONS, DEFAULT_STACK_ORDER
from .models import ActionBlock

def _base_kwargs(block_type: str, custom_id: str, defn: dict) -> dict:
    return {
        "id": custom_id or f"{block_type.lower()}_{uuid.uuid4().hex[:8]}",
        "block_id": block_type,
        "name": defn.get("name", block_type),
        "description": defn.get("description", ""),
        "icon": defn.get("icon", "extension"),
        "enabled": defn.get("default_enabled", True),
        "selector": defn.get("default_selector", ""),
        "label_selector": defn.get("default_label_selector", ""),
        "match_text": defn.get("default_match_text", ""),
        "match_mode": defn.get("default_match_mode", "contains"),
        "click_enabled": defn.get("default_click_enabled", True),
        "click_selector": defn.get("default_click_selector", ""),
        "fallback_selector": defn.get("default_fallback_selector", ""),
        "fallback_text": defn.get("default_fallback_text", ""),
        "highlight_enabled": defn.get("default_highlight_enabled", True),
        "color": defn.get("default_color", "#FF0000"),
        "required": defn.get("required", False),
        "category": defn.get("category", "action"),
    }


def _timing_kwargs(defn: dict) -> dict:
    return {
        "timeout_ms": defn.get("default_timeout_ms", 10000),
        "highlight_ms": defn.get("default_highlight_ms", 2000),
        "highlight_duration_ms": defn.get("default_highlight_ms", 2000),
        "pre_delay_ms": defn.get("default_pre_delay_ms", 200),
        "confirm_pause_ms": defn.get("default_confirm_pause_ms", 700),
    }


def _preset_kwargs(extra: dict) -> dict:
    return {
        "use_preset": extra.get("use_preset", False),
        "preset_name": extra.get("preset_name", ""),
        "overwrite": extra.get("overwrite", False),
        "include_prompt": extra.get("include_prompt", True),
        "include_job_id": extra.get("include_job_id", True),
        "suffix": extra.get("suffix", "_AI"),
        "duration_ms": extra.get("duration_ms", 1000),
        "load_from_preset": extra.get("load_from_preset", False),
        "extra": extra,
    }


def create_default_block(block_type: str, custom_id: str = None) -> "ActionBlock":
    defn = BLOCK_DEFINITIONS.get(block_type, {})
    extra = dict(defn.get("extra_defaults", {}))
    kw = {}
    kw.update(_base_kwargs(block_type, custom_id, defn))
    kw.update(_timing_kwargs(defn))
    kw.update(_preset_kwargs(extra))
    return ActionBlock(**kw)


def default_stack() -> List[ActionBlock]:
    return [create_default_block(bt) for bt in DEFAULT_STACK_ORDER]



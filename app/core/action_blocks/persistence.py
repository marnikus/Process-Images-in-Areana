from __future__ import annotations

from typing import Any, Dict, List, Optional
import copy
import json

from .definitions import BLOCK_DEFINITIONS, BUILTIN_BLOCKS, DEFAULT_STACK_ORDER, RETIRED_KEYS
from .factories import create_default_block, default_stack
from .models import ActionBlock

def _block_from_saved(d: Dict[str, Any]) -> Optional[ActionBlock]:
    """One saved entry → block, or None when corrupt (load is forgiving, never bricks)."""
    try:
        for rk in RETIRED_KEYS:
            d.pop(rk, None)
        if "block_id" in d:
            return ActionBlock.from_dict(d)
        bt = d.get("id") or ""
        if bt in BLOCK_DEFINITIONS:
            return create_default_block(bt, custom_id=d.get("id"))
        return ActionBlock.from_dict(d)
    except Exception:
        return None


def _append_missing_required(blocks: List[ActionBlock]) -> None:
    """Required blocks are always present: append defaults for anything absent."""
    existing_types = {b.block_id for b in blocks}
    for req_type, defn in BLOCK_DEFINITIONS.items():
        if defn.get("required") and req_type not in existing_types:
            blocks.append(create_default_block(req_type))


def load_stack_from_dicts(dicts: List[Dict[str, Any]]) -> List[ActionBlock]:
    blocks: List[ActionBlock] = []
    for d in dicts:
        if not isinstance(d, dict):
            continue
        block = _block_from_saved(d)
        if block is not None:
            blocks.append(block)
    _append_missing_required(blocks)
    return blocks


def stack_to_dicts(stack: List[ActionBlock]) -> List[Dict[str, Any]]:
    return [b.to_dict() for b in stack]


def validate_stack(stack: List[ActionBlock]) -> tuple[bool, str]:
    if not stack:
        return False, "Stack empty"
    types = {b.block_id: b for b in stack}
    for bt, defn in BLOCK_DEFINITIONS.items():
        if defn.get("required"):
            if bt not in types:
                return False, f"Required block {bt} missing"
            if not types[bt].enabled:
                return False, f"Required block {bt} disabled"
    return True, ""


def get_default_stack_json() -> str:
    return json.dumps(stack_to_dicts(default_stack()), ensure_ascii=False, indent=2)


def parse_stack_json(payload: str) -> List[ActionBlock]:
    try:
        data = json.loads(payload or "[]")
        if isinstance(data, list):
            return load_stack_from_dicts(data)
    except Exception:
        pass
    return default_stack()


def get_builtin_blocks_json() -> str:
    return json.dumps(BUILTIN_BLOCKS, ensure_ascii=False, indent=2)
def _is_other_preset(entry, clean: str) -> bool:
    """True for dict presets whose name survives an upsert."""
    return isinstance(entry, dict) and entry.get("name") != clean


def upsert_stack_preset(presets, name: str, blocks: list) -> list:
    """Upsert a named full-stack snapshot; latest save moves to the end."""
    clean = (name or "").strip()
    if not clean:
        raise ValueError("preset name required")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("stack must be a non-empty list")
    kept = [p for p in (presets or []) if _is_other_preset(p, clean)]
    kept.append({"name": clean, "blocks": copy.deepcopy(blocks)})
    return kept


def remove_stack_preset(presets, name: str) -> tuple:
    """Remove a named stack snapshot; (kept, removed?)."""
    kept = [p for p in (presets or []) if not (isinstance(p, dict) and p.get("name") == name)]
    before = len(presets) if isinstance(presets, list) else 0
    return kept, len(kept) != before

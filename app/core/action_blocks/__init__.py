# ideal-size: 60 lines reason=facade re-exports action_blocks package for backward compat per RULE 10
"""Action Blocks package — facade (split from 912 LOC file).

Public API preserved for existing imports.
Split into:
- definitions.py: BLOCK_DEFINITIONS, DEFAULT_STACK_ORDER, etc. (pure data, 565 LOC with override)
- models.py: ActionBlock dataclass (172 LOC with class-loc override)
- factories.py: create_default_block, default_stack
- persistence.py: load/stack helpers, presets
"""

from __future__ import annotations

from .definitions import (
    BLOCK_DEFINITIONS,
    BUILTIN_BLOCKS,
    DEFAULT_STACK_ORDER,
    DESCRIPTION_STACK_ORDER,
    RETIRED_KEYS,
)
from .factories import create_default_block, default_stack
from .models import ActionBlock
from .persistence import (
    get_builtin_blocks_json,
    get_default_stack_json,
    load_stack_from_dicts,
    parse_stack_json,
    remove_stack_preset,
    stack_to_dicts,
    upsert_stack_preset,
    validate_stack,
)

__all__ = [
    "ActionBlock",
    "BLOCK_DEFINITIONS",
    "BUILTIN_BLOCKS",
    "DEFAULT_STACK_ORDER",
    "DESCRIPTION_STACK_ORDER",
    "RETIRED_KEYS",
    "create_default_block",
    "default_stack",
    "load_stack_from_dicts",
    "stack_to_dicts",
    "validate_stack",
    "get_default_stack_json",
    "parse_stack_json",
    "get_builtin_blocks_json",
    "upsert_stack_preset",
    "remove_stack_preset",
]

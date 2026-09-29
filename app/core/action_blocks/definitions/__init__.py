# ideal-size: 40 lines reason=facade merging block definition submodules
from __future__ import annotations

from .keys import RETIRED_KEYS
from .registry import BLOCK_DEFINITIONS, BUILTIN_BLOCKS
from .stacks import DEFAULT_STACK_ORDER, DESCRIPTION_STACK_ORDER

__all__ = [
    "RETIRED_KEYS",
    "BLOCK_DEFINITIONS",
    "BUILTIN_BLOCKS",
    "DEFAULT_STACK_ORDER",
    "DESCRIPTION_STACK_ORDER",
]

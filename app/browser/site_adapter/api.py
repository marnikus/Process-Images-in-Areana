from __future__ import annotations
from typing import List
from ..selector import SelectorObject
from .registry import SELECTORS

def get_readiness_requirements() -> List[str]:
    return [
        "prompt_textarea",
        "send_button",
        "file_input",
        "output_region",
    ]

def get_selector(name: str) -> SelectorObject:
    if name not in SELECTORS:
        raise KeyError(f"Selector {name} not found")
    return SELECTORS[name]

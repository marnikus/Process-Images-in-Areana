"""Adapted from retained services/bot_variables.py: regex, one pass, visible unknowns.

No format/eval, filesystem access, recursive substitution or chat-context defaults.
Legacy aliases remain literal unless the user explicitly supplies their values.
"""

import re
from typing import Any

from image_queue.domain.validation import ContractError
from image_queue.workspace.libraries import validate_variables

PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def render_prompt(text: str, variables: dict[str, str], mode: str) -> dict[str, Any]:
    validate_variables(variables)
    if mode not in ("literal", "template") or not isinstance(text, str) or len(text) > 64000:
        raise ContractError("Invalid prompt text or mode")
    if mode == "literal":
        return {"text": text, "unknown": [], "malformed": [], "ok": True}
    unknown = list(dict.fromkeys(name for name in PATTERN.findall(text) if name not in variables))
    stripped = PATTERN.sub("", text)
    malformed = re.findall(r"\{[^{}]*\}", stripped)
    if stripped.count("{") != stripped.count("}"):
        malformed.append("unbalanced braces")
    rendered = _substitute(text, variables)
    return {
        "text": rendered,
        "unknown": unknown,
        "malformed": malformed,
        "ok": not unknown and not malformed,
    }


def _substitute(text: str, variables: dict[str, str]) -> str:
    size = len(text)

    def swap(match: re.Match[str]) -> str:
        nonlocal size
        value = variables.get(match[1], match[0])
        size += len(value) - len(match[0])
        if size > 1_000_000:
            raise ContractError("Rendered prompt exceeds safety limit")
        return value

    return PATTERN.sub(swap, text)

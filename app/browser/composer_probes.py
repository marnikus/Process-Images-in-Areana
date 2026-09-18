"""Active Arena prompt-composer insertion and verification probes."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_JS_DIR = Path(__file__).with_name("composer_js")


@lru_cache(maxsize=2)
def _probe(name: str) -> str:
    return (_JS_DIR / name).read_text(encoding="utf-8")


def build_insert_prompt_js(prompt: str) -> str:
    return f";({_probe('insert_prompt.js')})({json.dumps(prompt)})"


def build_verify_prompt_js(expected: str) -> str:
    return f";({_probe('verify_prompt.js')})({json.dumps(expected)})"

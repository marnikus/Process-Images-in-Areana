"""Shim for backward compat — new implementation lives in app.browser.cdp_arena (C3)."""
from .cdp_arena.controller import CDPArenaController
from .cdp_arena.js_snippets import (
    JS_INSERT_PROMPT,
    JS_SEND_STATE,
    JS_CLICK_SEND,
    JS_VERIFY_ATTACHMENT,
    JS_VERIFY_PROMPT,
    JS_FIND_TEXTAREA,
    JS_PAGE_READY,
    JS_SECURITY_DIALOG,
    JS_IS_GENERATING,
)

__all__ = [
    "CDPArenaController",
    "JS_INSERT_PROMPT",
    "JS_SEND_STATE",
    "JS_CLICK_SEND",
    "JS_VERIFY_ATTACHMENT",
    "JS_VERIFY_PROMPT",
    "JS_FIND_TEXTAREA",
    "JS_PAGE_READY",
    "JS_SECURITY_DIALOG",
    "JS_IS_GENERATING",
]

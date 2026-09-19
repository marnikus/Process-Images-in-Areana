"""CDP Arena package facade (C3) — re-exports controller + JS snippets for compat."""
from .controller import CDPArenaController
from .js_snippets import (
    JS_INSERT_PROMPT,
    JS_SEND_STATE,
    JS_CLICK_SEND,
    JS_VERIFY_ATTACHMENT,
    JS_VERIFY_PROMPT,
    JS_FIND_TEXTAREA,
    JS_DOWNLOAD_IMAGE,
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
    "JS_DOWNLOAD_IMAGE",
    "JS_PAGE_READY",
    "JS_SECURITY_DIALOG",
    "JS_IS_GENERATING",
]

"""Is this tab on a NEW chat? — asked before every job (I-74).

Owner request 2026-09-27: a job runs on whatever the tab shows, so a failed
post-job reset (or a chat the user opened) sent the next image into an old
conversation. One cheap probe (a 5 s `page_check`, I-73) reads what a
started conversation leaves on the page; `verdict` names every piece of it.

Evidence (selectors from site_adapter, RULE 21):
    path         under /c/ — a started conversation's address
    messages     the user's own messages (`user_message`, I-70)
    outputs      images from Arena's storage (src-based selectors only — a
                 promo card with `img.cursor-pointer` is never an output)
    composer     text left in the prompt box (-1: no prompt box at all)
    attachments  files attached in the composer form

Public API: build_chat_page_js(), verdict(state), read_chat_page(client).
Imports: same layer only.

ideal-size: ~95 lines — one question (is this a new chat?) and its words;
kept out of new_chat.py (the reset, 250 lines) so the reset does not grow.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional, Tuple

from . import page_recovery
from .probe_selectors import (attachment_preview_selectors, chat_output_selectors,
                              conversation_path_prefix, textarea_primary, user_message_selector)

_CHAT_PAGE_TEMPLATE = """;(() => {
  try {
    const most = (sels, root) => Math.max(0, ...sels.map((s) => {
      try { return root.querySelectorAll(s).length; } catch (e) { return 0; } }));
    const ta = document.querySelector(__TEXTAREA__);
    const form = ta ? ta.closest('form') : null;
    return {path: location.pathname,
            messages: document.querySelectorAll(__USER_MESSAGE__).length,
            outputs: most(__OUTPUTS__, document),
            attachments: form ? most(__ATTACHMENTS__, form) : 0,
            composer: ta ? ta.value.length : -1};
  } catch (e) { return {error: String(e)}; }
})()"""

_FIELDS = ("path", "messages", "outputs", "attachments", "composer")

# (is it there?, how it reads) — page order: address, conversation, prompt box.
_EVIDENCE: Tuple[Tuple[Callable[[dict], bool], Callable[[dict], str]], ...] = (
    (lambda s: str(s["path"]).startswith(conversation_path_prefix()),
     lambda s: f"a started chat ({s['path']})"),
    (lambda s: s["messages"] > 0, lambda s: f"{s['messages']} message(s) on the page"),
    (lambda s: s["outputs"] > 0, lambda s: f"{s['outputs']} generated image(s) on the page"),
    (lambda s: s["composer"] > 0, lambda s: f"the prompt box holds {s['composer']} characters"),
    (lambda s: s["composer"] < 0, lambda s: "no prompt box"),
    (lambda s: s["attachments"] > 0, lambda s: f"{s['attachments']} attached file(s)"),
)


def build_chat_page_js() -> str:
    """The probe with the adapter's selectors filled in."""
    fills = {"__TEXTAREA__": textarea_primary(), "__USER_MESSAGE__": user_message_selector(),
             "__OUTPUTS__": chat_output_selectors(), "__ATTACHMENTS__": attachment_preview_selectors()}
    js = _CHAT_PAGE_TEMPLATE
    for key, value in fills.items():
        js = js.replace(key, json.dumps(value))
    return js


def verdict(state: Any) -> Tuple[Optional[bool], str]:
    """(True, 'new chat') / (False, every piece of evidence) / (None, unreadable answer)."""
    state = _as_dict(state)
    if state is None or any(key not in state for key in _FIELDS):
        return None, f"the page did not say ({str(state)[:80]})"
    found = [words(state) for present, words in _EVIDENCE if present(state)]
    return (False, ", ".join(found)) if found else (True, "new chat")


def _as_dict(raw: Any) -> Optional[dict]:
    """CDP may hand the answer back as a dict or as its JSON text."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


async def read_chat_page(client: Any) -> Tuple[Optional[bool], str]:
    """One 5 s check of the tab; no answer is unknown, with the transport's reason."""
    try:
        state = await page_recovery.page_check(client, build_chat_page_js())
    except Exception as e:   # a broken client is an unknown page, never a crashed job
        return None, f"the page did not say ({type(e).__name__}: {e})"[:160]
    if state is None:
        return None, f"the page did not say ({page_recovery.evaluate_failure(client)[:120] or 'no answer'})"
    return verdict(state)

"""JS payloads the RDP console evaluates in the page (click-only scope).

Every payload is a self-contained expression that returns a JSON string, so
the caller never has to walk an ObjectActor grip: the console returns a plain
string result and the client parses it. One vocabulary for every answer —
`{"ok": bool, "reason": str, ...}` — so a miss is *empty* and a throw is
*broken* (RULE 4), never the same value.

Scope is deliberately narrow (the user's constraint): find an element and
click it. No typing, no navigation, no file input.

Layer: browser leaf — pure string builders, no sockets, no Qt.
"""

from __future__ import annotations

import json

__all__ = ["build_click_js", "build_probe_js", "build_webdriver_probe_js"]

# Real user-style click: the element is scrolled into view, then the full
# pointer/mouse sequence is dispatched by the browser itself. `.click()` alone
# skips the pointer events some UIs listen for.
_CLICK_BODY = """
(function () {
  try {
    var el = document.querySelector(SELECTOR);
    if (!el) return JSON.stringify({ok: false, reason: "not found"});
    var box = el.getBoundingClientRect();
    if (!box.width || !box.height) return JSON.stringify({ok: false, reason: "not visible"});
    if (el.disabled) return JSON.stringify({ok: false, reason: "disabled"});
    el.scrollIntoView({block: "center", inline: "center"});
    box = el.getBoundingClientRect();
    var x = box.left + box.width / 2, y = box.top + box.height / 2;
    var opts = {bubbles: true, cancelable: true, composed: true, view: window,
                clientX: x, clientY: y, button: 0, buttons: 1};
    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(function (name) {
      var Ctor = name.indexOf("pointer") === 0 && window.PointerEvent ? PointerEvent : MouseEvent;
      el.dispatchEvent(new Ctor(name, opts));
    });
    return JSON.stringify({ok: true, reason: "", x: Math.round(x), y: Math.round(y),
                           tag: el.tagName.toLowerCase()});
  } catch (e) {
    return JSON.stringify({ok: false, reason: "threw: " + e});
  }
})()
"""

_PROBE_BODY = """
(function () {
  try {
    var el = document.querySelector(SELECTOR);
    if (!el) return JSON.stringify({ok: false, reason: "not found"});
    var box = el.getBoundingClientRect();
    return JSON.stringify({ok: true, reason: "", visible: !!(box.width && box.height),
                           tag: el.tagName.toLowerCase(),
                           text: (el.textContent || "").trim().slice(0, 80)});
  } catch (e) {
    return JSON.stringify({ok: false, reason: "threw: " + e});
  }
})()
"""


def _with_selector(body: str, selector: str) -> str:
    """Inject `selector` as a JSON literal — never string-concatenated (injection-safe)."""
    return body.replace("SELECTOR", json.dumps(selector)).strip()


def build_click_js(selector: str) -> str:
    """Scroll to the first match and dispatch a full pointer+mouse click."""
    return _with_selector(_CLICK_BODY, selector)


def build_probe_js(selector: str) -> str:
    """Report whether the first match exists and is laid out (no interaction)."""
    return _with_selector(_PROBE_BODY, selector)


def build_webdriver_probe_js() -> str:
    """Read back the page's own automation signals — the stealth self-check (I-62).

    This is what the *site* sees. The pipeline asserts it stays clean, so a
    regression (someone adding `--marionette`) is caught by the app, loudly,
    instead of by the site silently blocking the account.
    """
    return ('JSON.stringify({webdriver: navigator.webdriver === true,'
            ' hasCdc: Object.keys(window).some(function (k) { return k.indexOf("cdc_") === 0; })})')

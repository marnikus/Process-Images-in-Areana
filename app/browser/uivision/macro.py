"""The Ui.Vision macro builder — the framework test `Python_XClick_Demo` (I-63).

The macro **never opens a page** (owner rule, 2026-09-23): `selectWindow` with
the run's tab target (`title=*pattern*`, wildcards per the selectWindow docs)
activates the already open tab — and because the Value column stays EMPTY, a
missing tab fails the run with the extension's own `E210` (`Status=Error` in
the savelog) instead of opening anything in a fresh tab.

The find step is one `executeScript` (the engine wraps the code in
`Promise.resolve(...)`, so the returned promise is awaited): it waits up to
the run's pause budget for the target element, then draws the app's RED find
rectangle (`#ff2d2d` — RULE 1's COLOR_FIND, the same outline the Chrome visual
runner draws) over the element's bounding box and holds it, so the owner SEES
the element was found before the native click fires. The script is **best
effort** and never fails the run — the XClick's own element lookup (the
extension's implicit wait, `!timeout_wait`) is the strict gate, and its
"timeout reached when waiting for element …" is the honest not-found verdict.
Targets that are not element locators (image `x.png@@0.8`, OCR text, raw `x,y`)
are skipped: the extension draws its own vision boxes for those.

The owner's critical rule: the click is **XClick** (native OS input through
the Desktop Automation XModule, `isTrusted: true`), never the DOM-level
`click` — so the builder refuses to emit any JS-level mouse command and a test
pins that. `bringBrowserToForeground` runs before the XClick because native
input lands where the OS pointer is (the official demo macros pair the two).

Per-run values ride the command line instead of the file — the extension seeds
exactly `!CMD_VAR1..3` (its override scope matches `^cmd_var(1|2|3)$`):
`${!cmd_var1}` is the pause budget in ms, `${!cmd_var2}` the XClick target,
`${!cmd_var3}` the tab target, so the macro on disk stays generic.

The JSON shape is Ui.Vision's own (`src/common/convert_utils.js toJSONString`):
`{"Name", "CreationDate", "Commands": [{"Command", "Target", "Value",
"Description"}]}` — hard-drive storage keeps it at `<home>/macros/<Name>.json`.
"""

from __future__ import annotations

import json
import re
from datetime import date

DEFAULT_MACRO_NAME = "Python_XClick_Demo"
PAUSE_VAR = "${!cmd_var1}"
TARGET_VAR = "${!cmd_var2}"
TAB_VAR = "${!cmd_var3}"
DONE_TEXT = "done — XClick fired (native OS input)"

# The macro's find-rectangle colour — RULE 1's COLOR_FIND: RED "element detected
# during FIND", the same outline the Chrome visual runner draws on the CDP path.
FIND_RECT_COLOR = "#ff2d2d"

# DOM-level mouse commands are banned by the owner's rule (they synthesize
# isTrusted:false events); XClick is the only click this macro may contain.
FORBIDDEN_COMMANDS = frozenset({
    "click", "clickandwait", "clickat", "doubleclick", "contextmenu",
    "mouseover", "mousedown", "mouseup",
})

# The name is a file path segment and a URL parameter — one safe grammar.
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")


def validate_macro_name(name) -> str:
    """A macro name that is safe as a file name and URL value (ValueError otherwise)."""
    text = (name or "").strip()
    if not NAME_PATTERN.match(text):
        raise ValueError(
            f"macro name {text!r} is not allowed — letters, digits, '_' and '-' only "
            f"(it becomes <home>/macros/<Name>.json)")
    return text


def command(name: str, target: str = "", value: str = "", description: str = "") -> dict:
    """One Ui.Vision command row."""
    return {"Command": name, "Target": target, "Value": value, "Description": description}


def refuse_dom_clicks(commands) -> None:
    """The critical rule as a gate: no DOM-level mouse command may ride a macro."""
    names = {str(c.get("Command") or "").strip().lower() for c in commands}
    bad = sorted(names & FORBIDDEN_COMMANDS)
    if bad:
        raise ValueError(f"DOM-level mouse commands are forbidden (use XClick): {', '.join(bad)}")


# The find-and-confirmation script (the 16.1.5 embedded-JS exception: one JS
# literal; the Python around it is trivial). `executeScript` renders
# `${!cmd_varN}` with JSON.stringify — both references below arrive in the page
# as ready string literals. Best effort by construction: every internal failure
# resolves to a "skipped"/"not found" answer, it never throws, and the XClick's
# own lookup is the strict gate (D-3). `FIND_RECT_COLOR` is injected so the
# RULE 1 colour has one owner in this module.
FIND_RECT_TEMPLATE = r"""(function () {
  var locator = ${!cmd_var2};
  var budget = Math.min(Math.max(parseInt(${!cmd_var1}, 10) || 3000, 1000), 25000);
  var m = String(locator).match(/^([A-Za-z_][A-Za-z0-9_-]*)=(.*)$/);
  if (!m) {
    return 'skipped: not an element locator (image/OCR/x,y) — the extension draws its own box';
  }
  var byXpath = function (xp) {
    var r = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
    return r ? r.singleNodeValue : null;
  };
  var find = function () {
    var kind = m[1].toLowerCase();
    var val = m[2];
    if (kind === 'xpath') return byXpath(val);
    if (kind === 'id') return document.getElementById(val);
    if (kind === 'css') return document.querySelector(val);
    if (kind === 'dom') return new Function('return (' + val + ');')();
    if (kind === 'text' || kind === 'link') {
      return byXpath("//*[contains(text(), '" + val.replace(/'/g, "\\'") + "')]");
    }
    return null;
  };
  var draw = function (el, ms) {
    try { el.scrollIntoView({ block: 'center' }); } catch (e) {}
    var box = el.getBoundingClientRect();
    var pad = 4;
    var rect = document.createElement('div');
    rect.setAttribute('style',
      'position:fixed; box-sizing:border-box; pointer-events:none; z-index:2147483647;' +
      ' border:3px solid __FIND_RECT_COLOR__; border-radius:6px;' +
      ' left:' + (box.left - pad) + 'px; top:' + (box.top - pad) + 'px;' +
      ' width:' + (box.width + pad * 2) + 'px; height:' + (box.height + pad * 2) + 'px;');
    (document.body || document.documentElement).appendChild(rect);
    setTimeout(function () { if (rect.parentNode) rect.parentNode.removeChild(rect); }, ms);
  };
  var t0 = Date.now();
  var drawn = false;
  return new Promise(function (resolve) {
    var done = false;
    var finish = function (msg) { if (!done) { done = true; resolve(msg); } };
    var tick = function () {
      var el = null;
      try { el = find(); } catch (e) { el = null; }
      if (el && !drawn) {
        drawn = true;
        try { draw(el, Math.max(500, budget - (Date.now() - t0))); } catch (e) {}
      }
      if (Date.now() - t0 >= budget) {
        finish(drawn ? 'element found — RED confirmation rectangle drawn'
                     : 'element not found within ' + budget + ' ms — the XClick gate decides');
        return;
      }
      setTimeout(tick, 200);
    };
    try { tick(); } catch (e) { finish('skipped: ' + e.message); }
  });
})()"""

FIND_RECT_JS = FIND_RECT_TEMPLATE.replace("__FIND_RECT_COLOR__", FIND_RECT_COLOR)


def render_find_rect_js(target: str, pause_ms) -> str:
    """FIND_RECT_JS with the per-run values rendered the way the extension does.

    The extension's `vars.render(..., shouldStringify)` substitutes each
    `${!cmd_varN}` with `JSON.stringify(value)` — a ready JS string literal.
    Mirroring that here lets the tests execute exactly what the page will eval
    (RULE 8), and locks the rendering contract in one place.
    """
    return (FIND_RECT_JS
            .replace(TARGET_VAR, json.dumps(str(target), ensure_ascii=False))
            .replace(PAUSE_VAR, json.dumps(str(int(pause_ms)))))


def build_commands(done_text: str = DONE_TEXT) -> list:
    """Reuse the run's tab (never open) → foreground → RED-rect confirm → XClick → done."""
    commands = [
        command("selectWindow", TAB_VAR, "",
                "reuse the already open tab matching cmd_var3 (title=*pattern*) — the Value "
                "column is EMPTY on purpose: nothing is ever opened, a missing tab fails "
                "the run (the extension's E210)"),
        command("bringBrowserToForeground", "", "",
                "native input needs Firefox visible and in front (owner's critical rule)"),
        command("executeScript", FIND_RECT_JS, "",
                "wait for the element (cmd_var1 ms) and draw the RED confirmation "
                "rectangle over it — best effort; the XClick lookup is the strict gate"),
        command("XClick", TARGET_VAR, "",
                "native OS click on the confirmed element (never DOM click)"),
        command("echo", done_text, "green", "completion marker — it lands in the savelog file"),
    ]
    refuse_dom_clicks(commands)
    return commands


def creation_date(today=None) -> str:
    """Ui.Vision's own date format: `YYYY-M-D`, no zero padding (toJSONString)."""
    day = today or date.today()
    return f"{day.year}-{day.month}-{day.day}"


def build_macro(name: str = DEFAULT_MACRO_NAME, done_text: str = DONE_TEXT,
                today=None) -> dict:
    """The macro document Ui.Vision reads from `<home>/macros/<Name>.json`."""
    return {"Name": validate_macro_name(name),
            "CreationDate": creation_date(today),
            "Commands": build_commands(done_text)}


def to_json(macro: dict) -> str:
    """The macro as the extension stores it (readable, stable key order)."""
    return json.dumps(macro, ensure_ascii=False, indent=2) + "\n"

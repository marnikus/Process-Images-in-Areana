"""The per-run pool macro — one Firefox job's commands, every value baked in (pure, I-64).

Unlike the framework test's generic macro (per-run values ride `cmd_var1..3`),
a pool run writes its own file (`{macro}_pool.json`, storage=xfile only; the
extension re-reads the file on every command-line run). The locator needs two
per-run values on top of the XClick target and the pause, and there is no
fourth `cmd_var`.

Order:
1. `selectWindow title=<anchor>` — the anchor tab; never opens a page.
2. Only when K > 0:
   - `bringBrowserToForeground` — focus the anchor's window;
   - `pause` — the autostart tab closes;
   - `selectWindow tab=K`.
   K = 0 never issues `tab=0`, which could hit a still-open autostart tab.
3. `executeScript` URL guard — throws on a page that is not a worker page.
4. The framework's tail: foreground → RED confirmation rect → XClick → echo.
   The DOM-click ban is enforced on the whole list (`refuse_dom_clicks`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..macro import (DONE_TEXT, command, creation_date, refuse_dom_clicks,
                     render_find_rect_js, validate_macro_name)

ANCHOR_SETTLE_MS = 1500   # > the autostart page's 500 ms self-close, with margin
POOL_SUFFIX = "_pool"

URL_GUARD_TEMPLATE = r"""(function () {
  var needle = __NEEDLE__;
  var href = String(location.href || '');
  if (href.toLowerCase().indexOf(needle.toLowerCase()) < 0) {
    throw new Error('not a worker page: ' + href + ' (its URL must contain ' + needle + ')');
  }
  return 'worker page: ' + href;
})()"""


@dataclass(frozen=True)
class PoolStep:
    """Everything one pool run bakes into its macro."""

    anchor: str        # the `title=` glob (locator.Address.anchor)
    offset: int        # K — tabs right of the anchor (0 = the anchor is the target)
    needle: str        # the pool URL pattern the page must contain ('' = no guard)
    target: str        # the XClick locator
    pause_ms: int      # the confirmation-rect budget


def pool_macro_name(base: str) -> str:
    """`{base}_pool` — kept apart from the framework test's generic macro."""
    return validate_macro_name(f"{validate_macro_name(base)}{POOL_SUFFIX}"[:64])


def url_guard_js(needle: str) -> str:
    """The URL check as the page will evaluate it (the needle is a JSON literal)."""
    return URL_GUARD_TEMPLATE.replace("__NEEDLE__", json.dumps(str(needle), ensure_ascii=False))


def _reach(step: PoolStep) -> list:
    """Anchor by title, then (K > 0) re-anchor on its window and step K tabs right."""
    rows = [command("selectWindow", f"title={step.anchor}", "",
                    "anchor: the nearest tab (at or left of the target) whose title is the "
                    "FIRST match in this profile — the Value is empty, nothing is opened")]
    if step.offset <= 0:
        return rows
    return rows + [
        command("bringBrowserToForeground", "", "",
                "focus the anchor's window — tab=N re-anchors on its active tab"),
        command("pause", str(ANCHOR_SETTLE_MS), "",
                "let the autostart tab close (it self-closes 500 ms after invoke)"),
        command("selectWindow", f"tab={step.offset}", "",
                f"the target: {step.offset} tab(s) right of the anchor, same window"),
    ]


def _guard(step: PoolStep) -> list:
    if not step.needle.strip():
        return []
    return [command("executeScript", url_guard_js(step.needle.strip()), "",
                    "refuse a page that is not a worker page — never click a stranger")]


def _tail(step: PoolStep) -> list:
    return [
        command("bringBrowserToForeground", "", "",
                "native input needs Firefox visible and in front (owner's critical rule)"),
        command("executeScript", render_find_rect_js(step.target, step.pause_ms), "",
                "wait for the element and draw the RED confirmation rectangle — best effort"),
        command("XClick", step.target, "", "native OS click (never a DOM click)"),
        command("echo", DONE_TEXT, "green", "completion marker — it lands in the savelog file"),
    ]


def build_pool_commands(step: PoolStep) -> list:
    """Reach the tab → guard its URL → the framework's foreground/confirm/XClick tail."""
    commands = _reach(step) + _guard(step) + _tail(step)
    refuse_dom_clicks(commands)
    return commands


def build_pool_macro(name: str, step: PoolStep, today=None) -> dict:
    """The document Ui.Vision reads from `<home>/macros/<name>.json` for ONE pool run."""
    return {"Name": validate_macro_name(name), "CreationDate": creation_date(today),
            "Commands": build_pool_commands(step)}

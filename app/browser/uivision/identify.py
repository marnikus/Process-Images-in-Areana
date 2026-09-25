"""The Firefox identify macro — read the signed-in account, draw the visual tab id.

Firefox tabs have no CDP client, so the Chrome owner probe and worker badge
cannot be evaluated directly. This module packs BOTH into one Ui.Vision
`executeScript` (the 16.1.5 embedded-JS exception: one JS literal, trivial
Python around it) and reads the answer back from the savelog:

  selectWindow  | ${!cmd_var3}            reuse the tab (never opens one — E210 if gone)
  executeScript | <IDENTIFY_JS>  | reply  probe (bounded in-page wait) + badge
  echo          | ARENA_IDENTITY=${reply} the answer lands in the savelog

Per-run values ride the command line, so the macro file stays generic:
`cmd_var1` = the in-page wait budget (ms), `cmd_var2` = JSON `{no, name, clear}`
(the visual worker number, the fallback display name, clear-only flag).
The probe is `owner_probe.build_owner_probe()` (RULE 21 selectors, one home)
and the badge is `worker_badge.build_badge_js_from` (one look, one attribute,
replace-before-insert → never two overlays). The reply carries only
`{email, via, overlay, text}` — the probe's text candidates are dropped, so no
unrelated page content reaches the savelog or the app log.

Imports: same layer only (owner_probe, worker_badge, sibling paths/macro/autorun).
"""

from __future__ import annotations

import json
import re

from ..owner_probe import build_owner_probe, interpret_owner
from ..worker_badge import BadgeExprs, build_badge_js_from, build_worker_badge_clear_js
from . import autorun, macro, paths

MACRO_NAME = "Arena_Identify"
REPLY_VAR = "arenaIdentity"
REPLY_MARK = "ARENA_IDENTITY="
WAIT_MS = 8000          # in-page wait for a still-loading sidebar (below !timeout_wait)
_REPLY_RE = re.compile(re.escape(REPLY_MARK) + r"(\{.*\})")

# ideal-size: 30-line JS literal reason=one executeScript payload; splitting the string
# would break the single-command Ui.Vision contract (RULE 16.1.5).
_IDENTIFY_TEMPLATE = r"""return (function () {
  var cfg = {};
  try { cfg = JSON.parse(${!cmd_var2}) || {}; } catch (e) { cfg = {}; }
  var budget = Math.min(Math.max(parseInt(${!cmd_var1}, 10) || 0, 0), 20000);
  var probe = function () {
    try { return JSON.parse(__PROBE__) || {}; } catch (e) { return {}; }
  };
  var t0 = Date.now();
  return new Promise(function (resolve) {
    var tick = function () {
      var r = cfg.clear ? {} : probe();
      var email = String(r.email || '');
      if (!cfg.clear && !email && Date.now() - t0 < budget) { setTimeout(tick, 400); return; }
      var name = email || String(cfg.name || '');
      var overlay = 'error';
      try { overlay = cfg.clear ? __CLEAR__ : __BADGE__; } catch (e) { overlay = 'error'; }
      resolve(JSON.stringify({email: email, via: String(r.via || ''), overlay: overlay,
                              text: cfg.clear ? '' : String(cfg.no) + '# ' + name}));
    };
    try { tick(); } catch (e) { resolve(JSON.stringify({email: '', via: 'error', overlay: 'error'})); }
  });
})()"""


def build_identify_js() -> str:
    """The executeScript body: probe (owner_probe) + badge (worker_badge), one reply."""
    badge = build_badge_js_from(BadgeExprs(no="String(cfg.no) + '#'", text="name",
                                           tag="String(cfg.no)"))
    return (_IDENTIFY_TEMPLATE
            .replace("__PROBE__", build_owner_probe())
            .replace("__CLEAR__", build_worker_badge_clear_js())
            .replace("__BADGE__", badge))


def render_identify_js(no: int, name: str, clear: bool = False) -> str:
    """The body with `${!cmd_var1..2}` rendered the way the extension does (tests, RULE 8)."""
    return (build_identify_js()
            .replace(macro.TARGET_VAR, json.dumps(payload(no, name, clear)))
            .replace(macro.PAUSE_VAR, json.dumps(str(WAIT_MS))))


def payload(no: int, name: str, clear: bool = False) -> str:
    """cmd_var2 — what the page needs to draw `<no># <name>` (or to clear the badge)."""
    return json.dumps({"no": int(no or 0), "name": str(name or ""), "clear": bool(clear)},
                      ensure_ascii=False)


def build_identify_macro() -> dict:
    """The macro document (`<home>/macros/Arena_Identify.json`)."""
    commands = [
        macro.command("selectWindow", macro.TAB_VAR, "",
                      "reuse the pooled tab (Value EMPTY: never opens a page — E210 if gone)"),
        macro.command("executeScript", build_identify_js(), REPLY_VAR,
                      "read the signed-in account (bounded wait) + draw the visual tab id"),
        macro.command("echo", REPLY_MARK + "${" + REPLY_VAR + "}", "blue",
                      "identify answer — the app reads it back from the savelog"),
    ]
    macro.refuse_dom_clicks(commands)
    return {"Name": MACRO_NAME, "CreationDate": macro.creation_date(), "Commands": commands}


def provision(spec) -> str:
    """Write the identify macro (hard-drive storage) + the shared autorun page; page path."""
    target = paths.macro_file(paths.home(spec.home), MACRO_NAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(macro.to_json(build_identify_macro()), encoding="utf-8")
    paths.logs_dir(spec.config_dir).mkdir(parents=True, exist_ok=True)
    return str(autorun.write_page(paths.autorun_file(spec.config_dir)))


def log_path(config_dir, stamp: str) -> str:
    """A savelog name of its own — an identify never shares a job's verdict file."""
    return str(paths.logs_dir(config_dir) / f"identify-{stamp}.txt")


def parse_reply(lines) -> dict:
    """Savelog lines → `{email, via, overlay, text}` (the LAST rendered answer wins).

    The unrendered `Executing: | echo | ARENA_IDENTITY=${…}` row never parses as
    JSON, so only the extension's rendered echo counts. No answer → empty dict.
    """
    for line in reversed(tuple(lines or ())):
        found = _REPLY_RE.search(str(line))
        reply = _decode(found.group(1)) if found else None
        if reply is not None:
            owner = interpret_owner(reply)
            return {"email": owner["email"], "via": owner["via"],
                    "overlay": str(reply.get("overlay", "") or ""),
                    "text": str(reply.get("text", "") or "")[:120]}
    return {}


def _decode(raw: str):
    """One JSON object or None (a torn or foreign line is simply not an answer)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None

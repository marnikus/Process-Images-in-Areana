"""Firefox display helpers — account probe + overlay via Ui.Vision macro (2026-09-25).

New macro integration for Firefox: the account email is read from the page's
DOM (evidence: ``div.font-heading.min-w-0.flex-1.truncate``) with the same
leaf-only, sidebar-scoped + heuristic scan as the CDP probe, but the JS is
rendered for ``executeScript`` inside a Ui.Vision macro (``isTrusted:true``
is not needed — the probe is read-only). The overlay reuses Chrome's visual
style (``worker_badge`` CSS) but is tagged ``data-arena-firefox-worker`` and
shows ``N# account`` per Firefox spec. Direct ``client.evaluate`` is tried
first (tests inject a fake client); when absent the macro is the reliable
fallback.

Imports: sibling uivision + ``app.browser`` selectors only — no services/UI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict

from app.browser.probe_selectors import account_email_probe
from app.core.tab_alias import email_from_probe, normalize_owner

# Macro building (reused from macro.py's shape) — avoids circular import by
# inlining the minimal command factory.
def _cmd(name: str, target: str = "", value: str = "", description: str = "") -> dict:
    return {"Command": name, "Target": target, "Value": value, "Description": description}


# The probe JS is the owner_probe logic, rendered for macro's executeScript.
# Keep leaf-only ownText() + sidebar heuristic, never inside composer.
_FIREFOX_PROBE_JS = r"""
(() => {
  try {
    const sels = __SELECTORS__;
    const scope = __SCOPE__;
    const out = {email: '', via: '', candidates: []};
    const RE = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}/;
    const SKIP = {SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, TEXTAREA: 1};
    const visible = (el) => {
      try {
        if (!el || el.nodeType !== 1 || !el.isConnected) return false;
        const cs = window.getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      } catch (e) { return false; }
    };
    const ownText = (el) => {
      let t = '';
      for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
      return (t || '').replace(/\s+/g, ' ').trim();
    };
    const inComposer = (el) => {
      let n = el;
      while (n && n.nodeType === 1) {
        if (SKIP[n.tagName] || n.isContentEditable) return true;
        n = n.parentElement;
      }
      return false;
    };
    const take = (el, via) => {
      if (!el || inComposer(el) || !visible(el)) return false;
      const text = ownText(el);
      if (!text || text.length > 80) return false;
      const found = text.match(RE);
      if (!found) return false;
      out.email = found[0];
      out.via = via;
      if (out.candidates.length < 4) out.candidates.push(text.slice(0, 80));
      return true;
    };
    const scan = (root, via) => {
      for (const sel of sels) {
        let els;
        try { els = (root || document).querySelectorAll(sel); } catch (e) { continue; }
        let seen = 0;
        for (const el of els) {
          if (seen++ > 50) break;
          if (take(el, via)) return true;
        }
      }
      return false;
    };
    if (scope) {
      let boxes = [];
      try { boxes = document.querySelectorAll(scope); } catch (e) { boxes = []; }
      for (const box of boxes) {
        if (scan(box, 'scope')) return JSON.stringify(out);
      }
    }
    if (scan(document, 'selector')) return JSON.stringify(out);
    let loose = [];
    try { loose = document.querySelectorAll('button, a, div, span, li'); } catch (e) { loose = []; }
    let seen = 0;
    for (const el of loose) {
      if (seen++ > 800) break;
      if (!el.closest('[data-sidebar], aside, nav, header')) continue;
      if (take(el, 'scan')) return JSON.stringify(out);
    }
    return JSON.stringify(out);
  } catch (e) {
    return JSON.stringify({email: '', via: 'error', error: String(e)});
  }
})()
"""


def build_firefox_account_probe_js() -> str:
    """JS that returns a JSON string ``{email, via, candidates}`` — macro-ready."""
    probe = account_email_probe()
    return (
        _FIREFOX_PROBE_JS.replace("__SELECTORS__", json.dumps(probe["selectors"])).replace(
            "__SCOPE__", json.dumps(probe["scope"])
        )
    )


def interpret_firefox_account(raw: Any) -> Dict[str, Any]:
    """Probe reply → ``{email, via}`` — never exposes HTML."""
    data: Any = raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw) if isinstance(raw, (bytes, bytearray)) else json.loads(raw)
        except Exception:
            # plain text fallback — extract email via tab_alias
            return {"email": email_from_probe(raw), "via": "unparseable"}
    if not isinstance(data, dict):
        return {"email": "", "via": "no_result"}
    return {"email": email_from_probe(data), "via": str(data.get("via", "") or "")}


# Macro integration for account detection — one selectWindow + executeScript + echo.
# The savelog's echoed JSON is the contract (Status=OK + echo line).
def build_firefox_account_macro(tab_selector: str) -> dict:
    """Macro JSON that selects the Firefox tab and echoes the account JSON."""
    tab_target = (tab_selector or "").strip() or "title=*arena.ai*"
    probe_js = build_firefox_account_probe_js()
    # executeScript stores result in !COL1 (Ui.Vision convention for return value capture)
    # We use Value column to name the variable, then echo it.
    commands = [
        _cmd("selectWindow", tab_target, "", "Firefox probe: reuse already open tab, never open"),
        _cmd("executeScript", probe_js, "fireProbe", "read account email from sidebar leaf text"),
        _cmd("echo", "${fireProbe}", "green", "probe result JSON lands in savelog"),
    ]
    return {"Name": "Firefox_Probe_Account", "CreationDate": "2026-09-25", "Commands": commands}


def build_firefox_overlay_macro(worker_no: int, account: str, tab_selector: str) -> dict:
    """Macro JSON that (re)draws the centered ``N# account`` overlay on the tab."""
    tab_target = (tab_selector or "").strip() or "title=*arena.ai*"
    # Reuse badge JS payload — macro's executeScript is the reliable fallback
    from app.browser.worker_badge import FirefoxBadgeSpec, build_firefox_badge_js

    js = build_firefox_badge_js(FirefoxBadgeSpec(worker_no=int(worker_no), account=str(account or "")))
    commands = [
        _cmd("selectWindow", tab_target, "", "Firefox overlay: reuse already open tab"),
        _cmd("bringBrowserToForeground", "", "", "overlay needs tab visible"),
        _cmd("executeScript", js, "", "draw centered N# account badge (idempotent)"),
    ]
    return {"Name": "Firefox_Overlay_Badge", "CreationDate": "2026-09-25", "Commands": commands}


@dataclass
class FirefoxDisplayCache:
    """Last verified display name with timestamp and source — for lifecycle."""

    display_name: str = ""
    source: str = ""  # detected | cached | profile | id
    seen_at: float = 0.0

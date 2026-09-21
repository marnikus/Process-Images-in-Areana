"""Logged-in-account probe — the readable half of a tab id (D-5).

Answers one question per call: "which account is this tab signed in as?".
The account row is visible in the site's sidebar (evidence in `site_adapter`
`account_email`), so the probe walks three widening nets:

  1. the site_adapter candidates, scoped to the sidebar first;
  2. the same candidates document-wide (a collapsed rail moves the row);
  3. a bounded heuristic over short texts inside any sidebar-ish container
     (`[data-sidebar]`, `aside`, `nav`, `header`) — never inside the composer,
     a textarea or a script, so the user's own prompt text can never label a tab.

RULE 21: every selector arrives from `probe_selectors.account_email_probe()`;
this file holds placeholders only. The reply is a JSON string
`{email, via, candidates}`; `interpret_owner` degrades to an empty answer.
Imports: probe_selectors (same layer) + core.tab_alias (downward).
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ..core.tab_alias import email_from_probe
from .probe_selectors import account_email_probe

_PROBE_JS = """
(() => {
  try {
    const sels = __SELECTORS__;
    const scope = __SCOPE__;
    const out = {email: '', via: '', candidates: []};
    const RE = /[A-Za-z0-9._%+\\-]+@[A-Za-z0-9\\-]+(?:\\.[A-Za-z0-9\\-]+)*\\.[A-Za-z]{2,}/;
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
      return (t || '').replace(/\\s+/g, ' ').trim();
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


def build_owner_probe() -> str:
    """JS (returns a JSON string) — `email`, `via`, `candidates`."""
    probe = account_email_probe()
    return (_PROBE_JS
            .replace("__SELECTORS__", json.dumps(probe["selectors"]))
            .replace("__SCOPE__", json.dumps(probe["scope"])))


def interpret_owner(raw: Any) -> Dict[str, Any]:
    """Probe reply (JSON string / dict / nothing) → `{email, via}`.

    No reply, a broken payload or any non-address answer reads as "unknown":
    the caller keeps the email it already had (a label never regresses).
    """
    data: Any = raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except Exception:
            return {"email": "", "via": "unparseable"}
    if not isinstance(data, dict):
        return {"email": "", "via": "no_result"}
    return {"email": email_from_probe(data), "via": str(data.get("via", "") or "")}

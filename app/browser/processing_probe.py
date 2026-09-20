"""Processing-indicator probe — AWAIT_PROCESSING_IMAGE (B12, 2026-10-08).

Answers one question per poll: "is the page still busy generating?". It is
NOT the new-output wait (output_probes): an idle page must answer `false`
at once, otherwise a wait placed before ATTACH_IMAGE burns its timeout.

Any one visible indicator ⇒ processing:
  * the site's processing spinner (site_adapter `processing_spinner`, RULE 21);
  * each comma-separated part of the block selector — a part written in the
    Playwright form `div:has-text("Processing")` (never valid CSS, so the
    block's default selector could never have been queried as-is) becomes
    `div` + own-text filter; a part the browser rejects is skipped, not fatal;
  * `match_text` — a short text node (≤ 40 chars) that STARTS with it
    ("Processing…", "Generating image"), so a sentence that merely contains
    the word (the user's own prompt bubble) never counts.
Imports: probe_selectors only (same layer).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .probe_selectors import spinner_selector

_HAS_TEXT_RE = re.compile(r""":has-text\((["'])(.*?)\1\)""")
_ANY = "*"

_PROBE_JS = """
(() => {
  try {
    const spinnerSel = __SPINNER__;
    const parts = __PARTS__;
    const matchText = __MATCH_TEXT__;
    const out = {processing: false, indicators: [], skipped: []};
    const visible = (el) => {
      try {
        if (!el || !el.isConnected || el.nodeType !== 1) return false;
        const cs = window.getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
        const r = el.getBoundingClientRect();
        if (!(r.width > 0 && r.height > 0)) return false;
        return el.offsetParent !== null || cs.position === 'fixed';
      } catch (e) { return false; }
    };
    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const ownText = (el) => {
      let t = '';
      for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
      return norm(t);
    };
    // A label ("Processing…") matches by its own text; a small wrapper
    // (<div><span>Generating…</span></div>) by its whole text when short.
    // Long containers (the user's prompt bubble) never match.
    const hasText = (el, text) => {
      const own = ownText(el);
      if (own && own.length <= 80 && own.includes(text)) return true;
      const all = norm(el.textContent);
      return all.length > 0 && all.length <= 40 && all.includes(text);
    };
    const note = (kind, sel, text) => {
      out.processing = true;
      if (out.indicators.length < 4) out.indicators.push({kind: kind, sel: sel, text: text || ''});
    };
    const firstVisible = (sel, text) => {
      let els;
      try { els = document.querySelectorAll(sel); } catch (e) { out.skipped.push(sel); return false; }
      for (const el of els) {
        if (!visible(el)) continue;
        if (text && !hasText(el, text)) continue;
        return true;
      }
      return false;
    };
    if (spinnerSel && firstVisible(spinnerSel, '')) note('spinner', spinnerSel, '');
    for (const p of parts) { if (firstVisible(p.sel, p.text)) note('selector', p.sel, p.text); }
    if (matchText && document.body) {
      const SKIP = {SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEXTAREA: 1, TITLE: 1, TEMPLATE: 1};
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n, seen = 0;
      while ((n = walker.nextNode()) && seen++ < 20000) {
        const t = (n.textContent || '').replace(/\\s+/g, ' ').trim();
        if (!t || t.length > 40 || !norm(t).startsWith(matchText)) continue;
        const p = n.parentElement;
        if (!p || SKIP[p.tagName] || !visible(p)) continue;
        note('text', p.tagName.toLowerCase(), t);
        break;
      }
    }
    return JSON.stringify(out);
  } catch (e) { return JSON.stringify({processing: false, error: String(e)}); }
})()
"""


_QUOTED_RE = re.compile(r""""[^"]*"|'[^']*'""")
_MASK_RE = re.compile("\x00(\\d+)\x00")
_DEPTH = {"(": 1, "[": 1, ")": -1, "]": -1}


def _mask_quotes(selector: str) -> tuple[str, List[str]]:
    """Quoted runs → \x00<n>\x00 placeholders so commas inside them are inert."""
    quoted: List[str] = []

    def _stash(m):
        quoted.append(m.group(0))
        return f"\x00{len(quoted) - 1}\x00"

    return _QUOTED_RE.sub(_stash, selector or ""), quoted


def _split_depth0(masked: str) -> List[str]:
    """Split on commas outside (…) / […] (quotes already masked)."""
    parts, buf, depth = [], [], 0
    for ch in masked:
        depth = max(0, depth + _DEPTH.get(ch, 0))
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def split_selector_list(selector: str) -> List[str]:
    """Top-level comma split that respects quotes and (…)/[…] nesting."""
    masked, quoted = _mask_quotes(selector)
    unmask = lambda s: _MASK_RE.sub(lambda m: quoted[int(m.group(1))], s).strip()  # noqa: E731
    return [p for p in (unmask(part) for part in _split_depth0(masked)) if p]


def selector_parts(selector: str) -> List[Dict[str, str]]:
    """[{sel, text}] per part; `x:has-text("T")` → sel `x` (or `*`) + text `t`."""
    out: List[Dict[str, str]] = []
    for part in split_selector_list(selector):
        m = _HAS_TEXT_RE.search(part)
        if not m:
            out.append({"sel": part, "text": ""})
            continue
        base = (part[:m.start()] + part[m.end():]).strip() or _ANY
        out.append({"sel": base, "text": m.group(2).strip().lower()})
    return out


def build_processing_probe(selector: str, match_text: str = "") -> str:
    """JS (returns a JSON string) — `processing`, `indicators`, `skipped`."""
    return (_PROBE_JS
            .replace("__SPINNER__", json.dumps(spinner_selector()))
            .replace("__PARTS__", json.dumps(selector_parts(selector)))
            .replace("__MATCH_TEXT__", json.dumps((match_text or "").strip().lower())))


def interpret_processing(raw: Any) -> Dict[str, Any]:
    """Probe reply (JSON string / dict / nothing) → dict with a bool `processing`.

    No reply and unparseable replies read as idle: this block exists to avoid
    acting DURING a generation, and a broken probe must never stall the run
    (that stall is the B12 defect)."""
    data: Any = raw
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except Exception:
            return {"processing": False, "indicators": [], "reason": "unparseable"}
    if not isinstance(data, dict):
        return {"processing": False, "indicators": [], "reason": "no_result"}
    data["processing"] = bool(data.get("processing"))
    data.setdefault("indicators", [])
    return data

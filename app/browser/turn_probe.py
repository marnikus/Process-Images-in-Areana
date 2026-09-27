"""Turn probe — find THIS job's finished image by the page's visual order (2026-09-27).

docs/archive/2026-09-27-chrome-output-detection-and-reset/design.md D-1/D-2.
The v4 check (`output_probes`) was run on the saved arena Direct-mode page in
real Chromium. It skips `blob:` outputs, misses a JOB-ID inside a prompt of
more than 2 000 characters, and anchors on sidebar chat titles. So with a
`blob:` output it chose the user's own attachment thumbnail as "the output".

This probe anchors on the text node that carries `JOB-ID: <id>]`. It takes the
lowest one on screen (the latest send) outside the chat chrome (sidebar,
header, composer), then reads the region down to the next prompt:

* a spinner or a "Generating image" status in the region means generating;
* an `<img>` shown at least MIN_SHOWN px wide and high is the output, whatever
  its src scheme (https / blob / data);
* smaller images are thumbnails (`refs`) and never outputs. `guard_thumbnail`
  refuses a v4 answer that picked one.

Selectors arrive from site_adapter (RULE 21); the payload is one JS literal
(RULE 16.1.5). Imports: probe_selectors only.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from .probe_selectors import chat_chrome_selectors, generating_status, spinner_selector

MIN_SHOWN = 200  # px on screen: generated outputs are shown large, attachment thumbnails at 128

_TURN_JS = r"""
((jobId, chromeSels, spinnerSel, gen, minShown) => {
  const out = {engine: 'turn', ready: false, turn_found: false, generating: false, spinning: false,
               reason: 'turn_not_found', expectedJobId: jobId, candidates: [], refs: []};
  try {
    if (!jobId) return out;
    const chrome = chromeSels.join(',');
    const inChrome = (el) => !!(el && el.closest && el.closest(chrome));
    const box = (el) => {
      for (let cur = el; cur; cur = cur.parentElement) {
        const r = cur.getBoundingClientRect();
        if (r.width > 0 || r.height > 0) return r;
      }
      return null;
    };
    const shown = (el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const esc = jobId.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const ours = new RegExp('JOB-ID:\\s*' + esc + '\\s*\\]');
    const anyJob = /JOB-ID:\s*[^\]\s]+\s*\]/;
    const prompts = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const text = n.nodeValue || '';
      if (!anyJob.test(text) || !n.parentElement || inChrome(n.parentElement)) continue;
      const r = box(n.parentElement);
      if (r) prompts.push({top: r.top, ours: ours.test(text)});
    }
    const mine = prompts.filter(p => p.ours);
    if (!mine.length) return out;
    const top = Math.max(...mine.map(p => p.top));
    const below = prompts.filter(p => p.top > top + 5).map(p => p.top);
    const next = below.length ? Math.min(...below) : Infinity;
    const inRegion = (r) => r.top > top && r.top < next;
    Object.assign(out, {turn_found: true, jobFound: true, jobTop: Math.round(top),
                        nextTop: next === Infinity ? null : Math.round(next), reason: 'turn_no_image'});
    for (const s of document.querySelectorAll(spinnerSel)) {
      if (!inChrome(s) && shown(s) && inRegion(s.getBoundingClientRect())) out.generating = true;
    }
    for (const el of document.querySelectorAll(gen.sels.join(','))) {
      if (el.children.length || inChrome(el) || !shown(el)) continue;
      if ((el.textContent || '').includes(gen.text) && inRegion(el.getBoundingClientRect())) out.generating = true;
    }
    for (const img of document.querySelectorAll('img')) {
      if (!img.src || inChrome(img)) continue;
      const r = img.getBoundingClientRect();
      if (r.width < minShown || r.height < minShown) {
        if (r.width > 0 && (img.naturalWidth || 0) >= 50 && out.refs.length < 10) out.refs.push(img.src);
        continue;
      }
      if (!inRegion(r)) continue;
      let opacity = 1;
      try { opacity = parseFloat(getComputedStyle(img).opacity); } catch (e) {}
      out.candidates.push({src: img.src, scheme: img.src.split(':')[0], w: img.naturalWidth || 0,
                           h: img.naturalHeight || 0, dw: Math.round(r.width), dh: Math.round(r.height),
                           complete: !!img.complete, opacity: opacity,
                           rect: {x: r.left, y: r.top, width: r.width, height: r.height}});
      if (!img.complete && img.loading === 'lazy' && img.scrollIntoView) img.scrollIntoView({block: 'nearest'});
    }
    out.spinning = out.generating;
    const done = out.candidates.filter(c => c.complete && c.w > 0 && c.opacity >= 0.5);
    if (out.generating) out.reason = 'turn_generating';
    else if (out.candidates.length && !done.length) out.reason = 'turn_image_loading';
    else if (done.length) {
      const best = done.reduce((a, b) => (b.w * b.h > a.w * a.h ? b : a));
      Object.assign(out, {ready: true, reason: '', src: best.src, width: best.w, height: best.h,
                          rect: best.rect, top: best.rect.y, isLarge: true, selector: 'job_turn',
                          associatedJobId: jobId,
                          orderCheck: `Turn probe: ${best.scheme} image ${best.w}x${best.h} below JOB-ID ${jobId} (top ${Math.round(top)})`});
    }
    return out;
  } catch (e) {
    out.reason = 'turn_error';
    out.error = String(e);
    return out;
  }
})
"""


def build_turn_js(correlation_id: str) -> str:
    """The probe call for one job id (selectors from site_adapter)."""
    args = [correlation_id or "", chat_chrome_selectors(), spinner_selector(), generating_status(), MIN_SHOWN]
    return ";(" + _TURN_JS.strip() + ")(" + ", ".join(json.dumps(a) for a in args) + ")"


async def read_turn(cdp, correlation_id) -> Dict[str, Any]:
    """One turn probe; {} when there is no job id or the page gave no answer (fail open)."""
    if not correlation_id:
        return {}
    try:
        res = await cdp.evaluate(build_turn_js(str(correlation_id)))
    except Exception:
        return {}
    return res if isinstance(res, dict) and res.get("engine") == "turn" else {}


def settles(turn: Dict[str, Any]) -> bool:
    """The turn answer stands on its own: a finished image, or generation still running."""
    return bool(turn.get("ready") or turn.get("generating"))


def guard_thumbnail(diag: Dict[str, Any], turn: Dict[str, Any]) -> Dict[str, Any]:
    """Refuse a v4 'ready' that picked a thumbnail (the user's own attachment)."""
    src = diag.get("src")
    if not diag.get("ready") or not src or src not in (turn.get("refs") or []):
        return diag
    return {"ready": False, "reason": "thumbnail_rejected", "src": src, "spinning": False,
            "expectedJobId": diag.get("expectedJobId"), "turn": summary(turn)}


def summary(turn: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, JSON-safe view of a turn answer for status lines and logs."""
    cands = [{k: c.get(k) for k in ("scheme", "w", "h", "dw", "dh", "complete", "opacity")}
             for c in (turn.get("candidates") or [])[:3]]
    return {"found": bool(turn.get("turn_found")), "reason": turn.get("reason", ""),
            "candidates": cands, "refs": len(turn.get("refs") or [])}

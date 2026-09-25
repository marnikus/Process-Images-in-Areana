"""Page-side JS for the Firefox image job — one expression per phase (2026-09-25).

Every body here is a plain JS *expression* (an async IIFE) that the phase
macro evaluates inside the pooled tab through the base64 loader in
`job_macros` (so Ui.Vision's `${…}` interpolation never touches it). The
probes are Chrome's own payloads, reused verbatim (design D-2, RULE 10):
`output_probes.build_baseline_js` / `build_check_js`, `js_snippets`
insert/verify/send-state/ready/generating/security, `page_errors`. Selectors
arrive from `probe_selectors` only (RULE 21).

The shared prelude adds four helpers the Chrome payloads lack: `__sha`
(SHA-256 hex, the prompt readback proof), `__previews` (visible attachment
previews, de-duplicated), `__composer` (the textarea value) and `__bubble`
(a text node carrying the JOB-ID marker outside the composer — proof that a
message was sent). Nothing here clicks: the clicks are XClick rows in the macro.
"""

from __future__ import annotations

import json

from ...utils.page_errors import build_error_scan_js
from ..cdp_arena.js_snippets import (
    JS_INSERT_PROMPT,
    JS_IS_GENERATING,
    JS_PAGE_READY,
    JS_SECURITY_DIALOG,
    JS_SEND_STATE,
)
from ..output_probes import build_baseline_js, build_check_js
from ..probe_selectors import attachment_preview_selectors, textarea_primary

STABLE_MS = 3000        # Chrome's "wait 3 s, re-check" before a result counts
POLL_MS = 1500

# ideal-size: 20-line JS literal reason=one prelude string shared by every phase body
_PRELUDE = r"""
  const __sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const __sha = async (text) => {
    const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(text)));
    return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, '0')).join('');
  };
  const __previews = () => {
    const out = []; const seen = new Set();
    for (const sel of __PREVIEW_SELS__) {
      for (const el of document.querySelectorAll(sel)) {
        if (el.offsetParent === null || seen.has(el)) continue;
        seen.add(el);
        out.push({alt: el.getAttribute('alt') || '', blob: (el.getAttribute('src') || '').startsWith('blob:')});
      }
    }
    return out;
  };
  const __composer = () => { const el = document.querySelector(__TEXTAREA__); return el ? el.value : null; };
  const __bubble = (marker) => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (n.parentElement && n.parentElement.closest('textarea')) continue;
      if ((n.nodeValue || '').indexOf(marker) >= 0) return true;
    }
    return false;
  };
  const __try = (fn, fallback) => { try { return fn(); } catch (e) { return fallback; } };
""".replace("__PREVIEW_SELS__", json.dumps(attachment_preview_selectors())) \
   .replace("__TEXTAREA__", json.dumps(textarea_primary()))


def expr(js: str) -> str:
    """A Chrome payload as a bare expression (drops the `;` guards at either end)."""
    return js.strip().strip(";").strip()


def marker(corr: str) -> str:
    """The JOB-ID marker `build_final_prompt` writes into the prompt."""
    return f"[JOB-ID: {corr}]"


def _body(code: str) -> str:
    """One async IIFE: prelude + phase code (the loader awaits the promise)."""
    return "(async () => {" + _PRELUDE + code + "\n})()"


def _security(in_scope: bool) -> str:
    """The captcha probe only while the Watcher is ON (RULE 20) — else constant false."""
    return f"__try(() => !!({expr(JS_SECURITY_DIALOG)}), false)" if in_scope else "false"


def baseline_js(in_scope: bool) -> str:
    """Outputs already on the page + readiness + composer state + errors (OBSERVE_BASELINE)."""
    return _body(f"""
  const b = __try(() => ({expr(build_baseline_js())}), {{}}) || {{}};
  const keep = (o) => ({{src: o.src, complete: o.complete, naturalWidth: o.naturalWidth,
    opacity: o.opacity, visible: o.visible, className: String(o.className || '').includes('opacity-0') ? 'opacity-0' : ''}});
  const composer = __composer();
  return {{outputs: (b.outputs || []).map(keep), srcs: b.output_srcs || [],
    ready: __try(() => ({expr(JS_PAGE_READY)}), {{ready: false, reasons: ['probe failed']}}),
    previews: __previews(), composer_len: composer === null ? -1 : composer.length,
    errors: __try(() => ({expr(build_error_scan_js())}), ''), security: {_security(in_scope)}}};""")


def attach_wait_js(name: str, budget_ms: int) -> str:
    """After the native dialog: wait for the preview named `name` (ATTACH/VERIFY_ATTACHMENT)."""
    return _body(f"""
  const name = {json.dumps(name)}; const t0 = Date.now();
  let p = __previews();
  while (!p.some((x) => x.alt === name) && Date.now() - t0 < {int(budget_ms)}) {{ await __sleep(400); p = __previews(); }}
  return {{previews: p, matched: p.filter((x) => x.alt === name).length}};""")


def prompt_js(prompt: str) -> str:
    """Insert with Chrome's native setter, read back, hash (INSERT/VERIFY_PROMPT)."""
    return _body(f"""
  const expected = {json.dumps(prompt, ensure_ascii=False)};
  const ins = __try(() => ({expr(JS_INSERT_PROMPT)})(expected), {{ok: false, error: 'insert threw'}});
  await __sleep(300);
  const actual = __composer();
  return {{ok: !!ins.ok && actual === expected, len: actual === null ? -1 : actual.length,
    sha256: await __sha(actual === null ? '' : actual), error: ins.error || (actual === null ? 'textarea not found' : '')}};""")


def guard_js(corr: str, prompt_sha: str, name: str) -> str:
    """Submit guard: our prompt + our preview + send enabled + NOT already sent."""
    return _body(f"""
  const composer = __composer();
  const sha = await __sha(composer === null ? '' : composer);
  const send = __try(() => ({expr(JS_SEND_STATE)})(), {{enabled: false}});
  const bubble = __bubble({json.dumps(marker(corr))});
  const promptOk = sha === {json.dumps(prompt_sha)};
  const attachmentOk = __previews().some((x) => x.alt === {json.dumps(name)});
  return {{go: !bubble && promptOk && attachmentOk && !!send.enabled, bubble: bubble,
    promptOk: promptOk, attachmentOk: attachmentOk, sendEnabled: !!send.enabled}};""")


def ack_js(corr: str, budget_ms: int) -> str:
    """After the XClick: the JOB-ID bubble (proof) or a cleared composer (weak ack)."""
    return _body(f"""
  const mark = {json.dumps(marker(corr))}; const t0 = Date.now();
  let bubble = __bubble(mark); let composer = __composer();
  while (!bubble && Date.now() - t0 < {int(budget_ms)}) {{
    await __sleep(400); bubble = __bubble(mark); composer = __composer();
  }}
  const cleared = composer !== null && composer.indexOf(mark) < 0;
  return {{ack: bubble ? 'bubble' : (cleared ? 'cleared' : ''), bubble: bubble,
    composer_len: composer === null ? -1 : composer.length}};""")


def _check_fn(corr: str, baseline: dict) -> str:
    """Chrome's strict JOB-ID check as a re-callable arrow (one call per poll)."""
    js = build_check_js(baseline.get("srcs") or [], corr, baseline.get("outputs") or [])
    return f"() => ({expr(js)})"


# ideal-size: 24 lines reason=one JS literal (the bounded observe loop) — splitting it breaks the in-page contract
def observe_js(corr: str, baseline: dict, window_ms: int, in_scope: bool) -> str:
    """Watch ≤ window_ms: a result counts only when the same src is ready twice, 3 s apart."""
    return _body(f"""
  const check = {_check_fn(corr, baseline)};
  const t0 = Date.now(); let prev = null; let last = {{}}; let found = false; let security = false;
  while (true) {{
    last = __try(check, {{ready: false, reason: 'probe failed'}}) || {{}};
    security = {_security(in_scope)};
    if (security) break;
    if (last.ready && last.src && prev === last.src) {{ found = true; break; }}
    prev = last.ready && last.src ? last.src : null;
    if (Date.now() - t0 >= {int(window_ms)}) break;
    await __sleep(prev ? {STABLE_MS} : {POLL_MS});
  }}
  const composer = __composer();
  const pick = (d) => ({{ready: !!d.ready, reason: d.reason || '', src: d.src || '',
    associatedJobId: d.associatedJobId || null, expectedJobId: d.expectedJobId || null,
    allNew: d.allNew || 0, spinning: !!d.spinning,
    mismatch: (d.mismatchDetails || []).slice(0, 5).map((m) => String(m.associated || '?'))}});
  return {{found: found, diag: pick(last), security: security,
    generating: __try(() => ({expr(JS_IS_GENERATING)}).isGenerating, false),
    errors: __try(() => ({expr(build_error_scan_js())}), ''),
    bubble: __bubble({json.dumps(marker(corr))}), previews: __previews(),
    composer_sha: await __sha(composer === null ? '' : composer)}};""")


def clean_js(budget_ms: int) -> str:
    """After New Chat: the `new_chat` clean-page rule (loaded, composer visible + empty, no preview)."""
    return _body(f"""
  const t0 = Date.now(); let state = {{}};
  while (true) {{
    const el = document.querySelector({json.dumps(textarea_primary())});
    state = {{loaded: document.readyState === 'complete', composer: !!el && el.offsetParent !== null,
      empty: !!el && el.value === '', previews: __previews().length}};
    if (state.loaded && state.composer && state.empty && !state.previews) return {{clean: true, state: state}};
    if (Date.now() - t0 >= {int(budget_ms)}) return {{clean: false, state: state}};
    await __sleep(500);
  }}""")


def security_js(in_scope: bool) -> str:
    """The captcha probe alone (the manual-security wait polls this)."""
    return _body(f"\n  return {{security: {_security(in_scope)}}};")

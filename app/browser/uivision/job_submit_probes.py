"""The Firefox image job's page probes, half two: prompt, submit guard, result.

Same contract as `job_probes` (one `executeScript` body per probe, values from
`${!cmd_var1}` / `${!cmd_var2}`, `render_*` reproduces the extension's own
rendering). These three carry the submit rules:

* `prompt` inserts the job's final prompt through the prototype's own value
  setter (React-safe) and reads it back — equality plus FNV-1a over UTF-16 code
  units, so a truncated or duplicated read-back is proved, never assumed.
* `guard` answers `"true"` only when the exact prompt is in the composer,
  exactly one attachment is named like the sent file, Send is enabled and no
  security dialog is up. The macro's `if | "${arenaGuard}" == "true"` sits
  directly in front of the single XClick Send.
* `result` waits for a candidate image that is NOT in the baseline, is not a
  blob, is not inside this job's own message and — when the `[JOB-ID: …]`
  container is found — sits after it. Ambiguity is reported, never resolved.

Imports: the sibling probe module only (one prelude owner).
"""

from __future__ import annotations

from . import job_probes

_PROMPT_TEMPLATE = r"""return (function () {
  __PRELUDE__
  var want = String(cfg.prompt || '');
  var ta = all(sel.textarea || [])[0] || null;
  if (!ta) return JSON.stringify({ok: false, reason: 'composer not found'});
  var had = valueOf(ta).length;
  var setValue = function (el, text) {
    try {
      var desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
      if (desc && desc.set) { desc.set.call(el, text); } else { el.value = text; }
    } catch (e) { el.value = text; }
    try { el.dispatchEvent(new Event('input', {bubbles: true})); } catch (e) {}
    try { el.dispatchEvent(new Event('change', {bubbles: true})); } catch (e) {}
  };
  var hashOf = function (text) {
    var h = 2166136261;
    for (var i = 0; i < text.length; i++) {
      var c = text.charCodeAt(i);
      h = Math.imul(h ^ (c & 0xff), 16777619) >>> 0;
      h = Math.imul(h ^ ((c >>> 8) & 0xff), 16777619) >>> 0;
    }
    return ('00000000' + h.toString(16)).slice(-8);
  };
  var attempts = Math.max(1, Math.min(3, parseInt(cfg.attempts, 10) || 2));
  var read = '', used = 0;
  for (var i = 0; i < attempts; i++) {
    setValue(ta, want);
    read = valueOf(ta);
    used = i + 1;
    if (read === want) break;
  }
  var occurrences = 0, at = want ? read.indexOf(want) : -1;
  while (at >= 0) { occurrences++; at = read.indexOf(want, at + want.length); }
  var ok = read === want;
  return JSON.stringify({ok: ok,
    reason: ok ? 'matched' : (read.length < want.length ? 'truncated read-back' : 'read-back differs'),
    len: read.length, expected_len: want.length, hash: hashOf(read),
    expected_hash: String(cfg.expect || ''), occurrences: occurrences,
    had_previous: had, attempts: used, head: read.slice(0, 40), tail: read.slice(-40)});
})()"""

_GUARD_TEMPLATE = r"""return (function () {
  __PRELUDE__
  if (securityOn()) return 'false';
  var ta = all(sel.textarea || [])[0] || null;
  if (!ta) return 'false';
  var want = String(cfg.prompt || '');
  if (valueOf(ta) !== want) return 'false';
  var nodes = previewsNow();
  if (nodes.length !== 1) return 'false';
  var wantFile = String(cfg.file || '').toLowerCase();
  var alt = String(nodes[0].alt || '').toLowerCase();
  var named = !!alt ? (alt === wantFile || alt.indexOf(wantFile) >= 0 || wantFile.indexOf(alt) >= 0) : !!nodes[0].blob;
  if (!named) return 'false';
  var send = all(sel.send || [])[0] || null;
  if (!enabled(send)) return 'false';
  return 'true';
})()"""

# The guard's *reason* is a second, read-only pass: it never gates the click, it
# explains a refusal in the app log (one honest sentence per cause).
_GUARD_WHY_TEMPLATE = r"""return (function () {
  __PRELUDE__
  if (securityOn()) return 'security dialog visible';
  var ta = all(sel.textarea || [])[0] || null;
  if (!ta) return 'composer not found';
  var want = String(cfg.prompt || '');
  var read = valueOf(ta);
  if (read !== want) return 'prompt read-back differs (' + read.length + '/' + want.length + ' chars)';
  var nodes = previewsNow();
  if (nodes.length !== 1) return nodes.length + ' attachment(s) on the page, expected exactly 1';
  var wantFile = String(cfg.file || '').toLowerCase();
  var alt = String(nodes[0].alt || '').toLowerCase();
  var named = !!alt ? (alt === wantFile || alt.indexOf(wantFile) >= 0 || wantFile.indexOf(alt) >= 0) : !!nodes[0].blob;
  if (!named) return 'attached file is not ' + wantFile;
  var send = all(sel.send || [])[0] || null;
  if (!send) return 'send button not found';
  if (!enabled(send)) return 'send button disabled';
  return 'ready';
})()"""

_RESULT_TEMPLATE = r"""return (function () {
  __PRELUDE__
  var token = String(cfg.token || '');
  var baseline = cfg.baseline || [];
  var userBubble = function (el) {
    try { return String(el.className || '').indexOf('items-end') >= 0; } catch (e) { return false; }
  };
  var tokenEl = function () {
    if (!token) return null;
    var nodes = all(sel.blocks || []);
    for (var i = nodes.length - 1; i >= 0; i--) {
      var el = nodes[i];
      var tag = String(el.tagName || '');
      if (tag === 'TEXTAREA' || tag === 'SCRIPT' || tag === 'STYLE') continue;
      var text = String(el.textContent || '');
      if (text.length > 2000 || text.indexOf(token) < 0) continue;
      return el;
    }
    return null;
  };
  var containerOf = function (el) {
    try {
      var cur = el;
      for (var i = 0; i < 12 && cur; i++) {
        if (!cur.getBoundingClientRect) { cur = cur.parentElement; continue; }
        var r = cur.getBoundingClientRect();
        if (r.height < 20) { cur = cur.parentElement; continue; }
        if (r.height > window.innerHeight * 0.95 || r.width > window.innerWidth * 0.98) {
          cur = cur.parentElement; continue;
        }
        if (cur.querySelector && cur.querySelector('img')) return cur;
        if (cur.classList && (cur.classList.contains('flex') || cur.classList.contains('group'))) return cur;
        cur = cur.parentElement;
      }
    } catch (e) {}
    return el;
  };
  var describe = function (el, jobEl) {
    var rect = {width: 0, height: 0};
    try { rect = el.getBoundingClientRect(); } catch (e) {}
    var inUser = false;
    try { inUser = !!(jobEl && jobEl.contains(el)); } catch (e) {}
    var after = false;
    if (jobEl && !inUser) {
      try { after = !!(jobEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING); }
      catch (e) { after = true; }
    }
    var cls = String(el.className || '');
    var nat = el.naturalWidth || 0;
    var large = rect.width >= 200 || nat >= 200 || cls.indexOf('50vh') >= 0
      || cls.indexOf('aspect-square') >= 0 || cls.indexOf('object-cover') >= 0;
    return {src: String(el.currentSrc || el.src || ''), w: Math.round(rect.width), h: Math.round(rect.height),
            nat: nat, after: after, in_user: inUser, large: large, blob: false,
            alt: String(el.alt || '').slice(0, 60)};
  };
  var t0 = Date.now();
  return new Promise(function (resolve) {
    var tick = function () {
      var tokenNode = tokenEl();
      var jobEl = tokenNode ? containerOf(tokenNode) : null;
      var nodes = all(sel.output || []);
      var fresh = [], seen = {};
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        var raw = String(el.currentSrc || el.src || '');
        if (!raw) continue;
        var info = describe(el, jobEl);
        info.blob = raw.indexOf('blob:') === 0;
        if (info.blob || baseline.indexOf(raw) >= 0 || seen[info.src]) continue;
        seen[info.src] = 1;
        fresh.push(info);
      }
      var spinning = spinningOn();
      var elapsed = Date.now() - t0;
      var settled = !spinning && fresh.length > 0;
      if (!settled && !securityOn() && elapsed < budget) { setTimeout(tick, 500); return; }
      resolve(JSON.stringify({ok: fresh.length > 0, token_seen: !!tokenNode, spinning: spinning,
                              security: securityOn(), timed_out: fresh.length === 0,
                              elapsed_ms: elapsed, candidates: fresh.slice(0, 8),
                              total_imgs: nodes.length, user_bubble: jobEl ? userBubble(jobEl) : false}));
    };
    try { tick(); } catch (e) { resolve(JSON.stringify({ok: false, reason: 'error: ' + e.message})); }
  });
})()"""


def build_prompt_js() -> str:
    """`executeScript` body: insert the final prompt, then read it back."""
    return job_probes.body(_PROMPT_TEMPLATE)


def render_prompt_js(payload_json: str, budget_ms: int = 5000) -> str:
    return job_probes.rendered(_PROMPT_TEMPLATE, payload_json, budget_ms)


def build_guard_js() -> str:
    """`executeScript` body: exactly `"true"` when the pre-submit checkpoint holds."""
    return job_probes.body(_GUARD_TEMPLATE)


def render_guard_js(payload_json: str, budget_ms: int = 5000) -> str:
    return job_probes.rendered(_GUARD_TEMPLATE, payload_json, budget_ms)


def build_guard_why_js() -> str:
    """`executeScript` body: the refusal's reason, read-only (never gates the click)."""
    return job_probes.body(_GUARD_WHY_TEMPLATE)


def render_guard_why_js(payload_json: str, budget_ms: int = 5000) -> str:
    return job_probes.rendered(_GUARD_WHY_TEMPLATE, payload_json, budget_ms)


def build_result_js() -> str:
    """`executeScript` body: wait for the correlated, not-in-baseline output image."""
    return job_probes.body(_RESULT_TEMPLATE)


def render_result_js(payload_json: str, budget_ms: int) -> str:
    return job_probes.rendered(_RESULT_TEMPLATE, payload_json, budget_ms)

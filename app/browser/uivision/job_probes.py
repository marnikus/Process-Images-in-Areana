"""The Firefox image job's page probes, half one: state, locator, attachment, bytes.

Every payload is one `executeScript` body (the 16.1.5 embedded-JS exception: the
payload IS a literal) whose per-run values ride the published command-line
contract — `${!cmd_var1}` = the in-page budget in ms, `${!cmd_var2}` = the JSON
payload (`job_macro.payload` builds it; RULE 21 selectors arrive inside it, no
selector literal lives here). The extension substitutes each with
`JSON.stringify(value)`, so `render_*` below reproduces exactly what the page
will eval (RULE 8 — the JS lane executes these strings).

The probes only **observe and locate**: the answer is a JSON string (or, for
`fetch`, the base64 of the correlated image). Clicks stay in the macro and go
through XClick; the probe's job is to hand the macro a locator it can trust
(`xpath=…` computed from the element the site_adapter list found) and to hand
the app the facts it decides on (`uivision.job_replies`).

Imports: stdlib only.
"""

from __future__ import annotations

import json

from . import macro as uv_macro

# Shared prelude: payload, budget, the shape rules all probes agree on.
# `securityOn`/`spinningOn` read the *page*, never a hard-coded phrase — the
# dialog's own text marker arrives in the payload (site_adapter owns it).
_PRELUDE = r"""var cfg = {};
try { cfg = JSON.parse(${!cmd_var2}) || {}; } catch (e) { cfg = {}; }
var sel = cfg.sel || {};
var budget = Math.min(Math.max(parseInt(${!cmd_var1}, 10) || 1000, 200), 600000);
var all = function (list) {
  var out = [];
  (list || []).forEach(function (s) {
    try {
      Array.prototype.forEach.call(document.querySelectorAll(s), function (el) {
        if (out.indexOf(el) < 0) out.push(el);
      });
    } catch (e) {}
  });
  // document order, and one entry per element: the site_adapter lists overlap
  // (a blob tile with an alt matches two of them) and Chrome's single
  // `querySelectorAll(list.join(','))` returns each element exactly once
  out.sort(function (a, b) {
    try { return (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) ? -1 : 1; }
    catch (e) { return 0; }
  });
  return out;
};
var visible = function (el) {
  try { return el.offsetParent !== null && el.getBoundingClientRect().width > 0; }
  catch (e) { return false; }
};
var valueOf = function (el) { return el && typeof el.value === 'string' ? el.value : ''; };
var enabled = function (el) { return !!el && !el.disabled && el.getAttribute('aria-disabled') !== 'true'; };
var securityOn = function () {
  var d = all(sel.security || [])[0];
  if (!d || !visible(d)) return false;
  var want = String(cfg.secText || '');
  return !want || String(d.textContent || '').indexOf(want) >= 0;
};
var spinningOn = function () { return Array.prototype.some.call(all(sel.spinner || []), visible); };
var previewsNow = function () {
  return all(sel.preview || []).map(function (el) {
    return {alt: String(el.alt || ''), src: String(el.src || ''),
            blob: String(el.src || '').indexOf('blob:') === 0};
  });
};
var xpathOf = function (el) {
  try {
    var parts = [], cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 30) {
      var idx = 1, sib = cur.previousElementSibling;
      while (sib) { if (sib.tagName === cur.tagName) idx++; sib = sib.previousElementSibling; }
      parts.unshift(String(cur.tagName || '').toLowerCase() + '[' + idx + ']');
      cur = cur.parentElement;
    }
    return parts.length ? 'xpath=/' + parts.join('/') : '';
  } catch (e) { return ''; }
};
var snapshot = function () {
  var ta = all(sel.textarea || [])[0] || null;
  var text = valueOf(ta);
  var srcs = all(sel.output || []).map(function (el) { return String(el.currentSrc || el.src || ''); });
  var uniq = srcs.filter(function (s, i) { return !!s && srcs.indexOf(s) === i; });
  var previews = previewsNow();
  var spinning = spinningOn();
  var security = securityOn();
  return {ok: true, url: String(location.href || ''), ready: String(document.readyState || ''),
          srcs: uniq, previews: previews, textarea: !!ta,
          composer: {len: text.length, head: text.slice(0, 40), tail: text.slice(-40)},
          send: !!all(sel.send || []).length, newchat: !!all(sel.newchat || []).length,
          spinning: spinning, security: security,
          clean: !!ta && text.length === 0 && previews.length === 0 && !spinning && !security
                 && String(document.readyState || '') === 'complete'};
};"""

# `until: "ready"` waits for a usable composer (a reloaded tab needs it);
# `until: "clean"` is the New-chat verification. Anything else answers at once
# (the recovery probe must never wait for a page that will not change).
_STATE_TEMPLATE = r"""return (function () {
  __PRELUDE__
  var want = String(cfg.until || '');
  var usable = function (now) {
    return now.textarea && now.ready === 'complete' && !now.security
           && (want !== 'ready' || (now.send && now.newchat));
  };
  var t0 = Date.now();
  return new Promise(function (resolve) {
    var tick = function () {
      var now;
      try { now = snapshot(); } catch (e) { resolve(JSON.stringify({ok: false, reason: 'error: ' + e.message})); return; }
      now.elapsed_ms = Date.now() - t0;
      now.until = want;
      if (want !== 'ready' && want !== 'clean') { resolve(JSON.stringify(now)); return; }
      var done = want === 'clean' ? now.clean : usable(now);
      if (done || now.elapsed_ms >= budget) { resolve(JSON.stringify(now)); return; }
      setTimeout(tick, 300);
    };
    try { tick(); } catch (e) { resolve(JSON.stringify({ok: false, reason: 'error: ' + e.message})); }
  });
})()"""

# The attachment proof: a preview that was NOT there before the dialog AND whose
# alt matches the file we sent, with NO other tile on the page — a leftover from
# a previous job would ride along into the submission, so it is a refusal, never
# a pass. `alt` empty is accepted only for a fresh blob tile (the site's own
# rendering of the local file).
_ATTACH_TEMPLATE = r"""return (function () {
  __PRELUDE__
  var want = String(cfg.file || '').toLowerCase();
  var before = cfg.before || [];
  var key = function (p) { return String(p.alt || '') + '|' + String(p.src || ''); };
  var matches = function (p) {
    var alt = String(p.alt || '').toLowerCase();
    if (!alt) return !!p.blob;
    return alt === want || alt.indexOf(want) >= 0 || want.indexOf(alt) >= 0;
  };
  var names = function (nodes) {
    return nodes.map(function (p) { return String(p.alt || '') || '(unnamed)'; }).slice(0, 3).join(', ');
  };
  var t0 = Date.now();
  return new Promise(function (resolve) {
    var tick = function () {
      if (securityOn()) { resolve(JSON.stringify({ok: false, reason: 'security dialog visible', security: true})); return; }
      var nodes = previewsNow();
      var fresh = nodes.filter(function (p) { return before.indexOf(key(p)) < 0; });
      var elapsed = Date.now() - t0;
      if (fresh.length === 1 && nodes.length === 1 && matches(fresh[0])) {
        resolve(JSON.stringify({ok: true, reason: 'verified', found: fresh[0], count: 1,
                                stale: 0, elapsed_ms: elapsed}));
        return;
      }
      if (fresh.length && elapsed >= 1000) {
        resolve(JSON.stringify({ok: false, fresh: fresh, count: nodes.length,
                                stale: nodes.length - fresh.length, elapsed_ms: elapsed,
                                reason: fresh.length > 1
                                  ? fresh.length + ' attachments appeared — expected exactly 1'
                                    + (before.length ? '' : ' (a stale tile from an earlier job?)')
                                  : 'wrong file attached: ' + names(fresh)}));
        return;
      }
      if (!fresh.length && elapsed >= budget) {
        resolve(JSON.stringify({ok: false, count: nodes.length, stale: nodes.length,
                                elapsed_ms: elapsed,
                                reason: nodes.length
                                  ? 'stale attachment from a previous job (' + names(nodes) + ')'
                                  : 'no attachment preview'}));
        return;
      }
      setTimeout(tick, 300);
    };
    try { tick(); } catch (e) { resolve(JSON.stringify({ok: false, reason: 'error: ' + e.message})); }
  });
})()"""

# One element locator for the macro's XClick: the site_adapter list finds it,
# the probe answers with an absolute xpath the extension resolves natively.
#
# The answer is the BARE locator (or ''), never a JSON envelope: this variable
# rides straight into the macro's `if "${arenaX}" != ""` guard and into the
# `XClick ${arenaX}` target, and Ui.Vision evaluates the `if` target as
# JavaScript (`executeScript_Sandbox`) — a JSON answer puts its own `"` inside
# that quoted condition and the whole macro dies with
# `Status=Error: Unexpected token (1:N)` before anything is attached
# (2026-09-26, live report: the prepare stage failed in 4–6 s, every job).
# `job_replies.locate_verdict` reads the same variable from the savelog, so the
# bare shape is the ONE contract both sides share.
_LOCATE_TEMPLATE = r"""return (function () {
  __PRELUDE__
  var nodes = all(cfg.list || []).filter(function (el) {
    if (cfg.visible !== false && !visible(el)) return false;
    if (cfg.enabledOnly && !enabled(el)) return false;
    return true;
  });
  var pick = String(cfg.pick || 'first') === 'last' ? nodes[nodes.length - 1] : nodes[0];
  return pick ? xpathOf(pick) : '';
})()"""

# The bytes of the correlated image, exactly in Chrome's order: in-page fetch
# (credentials included), then the page's own <img> through a canvas. The answer
# carries the base64 — the savelog is the only channel a macro has.
_FETCH_TEMPLATE = r"""return (function () {
  __PRELUDE__
  var want = String(cfg.src || '');
  var findImg = function () {
    var nodes = document.querySelectorAll('img');
    for (var i = nodes.length - 1; i >= 0; i--) {
      if (String(nodes[i].currentSrc || nodes[i].src || '') === want) return nodes[i];
    }
    return null;
  };
  var toB64 = function (bytes) {
    var out = '';
    for (var i = 0; i < bytes.length; i += 32768) {
      out += String.fromCharCode.apply(null, bytes.subarray(i, i + 32768));
    }
    return btoa(out);
  };
  var canvasB64 = function (el) {
    var w = el.naturalWidth || el.width, h = el.naturalHeight || el.height;
    if (!w || !h) throw new Error('image has no pixels yet');
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    c.getContext('2d').drawImage(el, 0, 0, w, h);
    return String(c.toDataURL('image/png').split(',')[1] || '');
  };
  var done = function (ok, method, data, note) {
    return JSON.stringify({ok: ok, method: method, src: want, len: String(data || '').length,
                           b64: String(data || ''), note: String(note || '')});
  };
  return Promise.resolve()
    .then(function () { return fetch(want, {credentials: 'include', mode: 'cors'}); })
    .then(function (res) { if (!res.ok) throw new Error('status ' + res.status); return res.arrayBuffer(); })
    .then(function (buf) { return done(true, 'fetch', toB64(new Uint8Array(buf)), ''); })
    .catch(function (err) {
      var el = findImg();
      if (!el) { return done(false, 'canvas', '', 'no <img> for this src (' + err.message + ')'); }
      try { return done(true, 'canvas', canvasB64(el), ''); }
      catch (e2) { return done(false, 'canvas', '', err.message + ' / ' + e2.message); }
    });
})()"""


def body(template: str) -> str:
    """The payload with the shared prelude in place (placeholders intact)."""
    return template.replace("__PRELUDE__", _PRELUDE)


def rendered(template: str, payload_json: str, budget_ms) -> str:
    """The body exactly as the extension renders it (tests execute this, RULE 8)."""
    return (body(template)
            .replace(uv_macro.TARGET_VAR, json.dumps(str(payload_json), ensure_ascii=False))
            .replace(uv_macro.PAUSE_VAR, json.dumps(str(int(budget_ms or 0)))))


def build_state_js() -> str:
    """`executeScript` body: composer + previews + output srcs + flags (baseline)."""
    return body(_STATE_TEMPLATE)


def render_state_js(payload_json: str, budget_ms: int) -> str:
    return rendered(_STATE_TEMPLATE, payload_json, budget_ms)


def build_attach_js() -> str:
    """`executeScript` body: wait for exactly one NEW preview matching the file name."""
    return body(_ATTACH_TEMPLATE)


def render_attach_js(payload_json: str, budget_ms: int) -> str:
    return rendered(_ATTACH_TEMPLATE, payload_json, budget_ms)


def build_locate_js() -> str:
    """`executeScript` body: turn one site_adapter list into an `xpath=` locator."""
    return body(_LOCATE_TEMPLATE)


def render_locate_js(payload_json: str, budget_ms: int = 4000) -> str:
    return rendered(_LOCATE_TEMPLATE, payload_json, budget_ms)


def build_fetch_js() -> str:
    """`executeScript` body: fetch → canvas, answering the image's base64."""
    return body(_FETCH_TEMPLATE)


def render_fetch_js(payload_json: str, budget_ms: int) -> str:
    return rendered(_FETCH_TEMPLATE, payload_json, budget_ms)

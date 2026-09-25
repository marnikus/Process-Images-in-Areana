"""Page snapshots the Firefox image-job macros read back (I-65).

One `executeScript` per probe (the 16.1.5 embedded-JS exception: the bodies
are string literals; the Python around them only fills RULE 21 selectors).
The script is a function body — Ui.Vision wraps it the same way it wraps
`Arena_Identify` (`return …`). No DOM click is emitted here.

Imports: sibling probe_selectors only.
"""

from __future__ import annotations

import json

from ..probe_selectors import (
    attachment_preview_selectors,
    output_image_selectors,
    send_presence_selector,
    spinner_selector,
    textarea_primary,
)

# Security is a visible challenge frame — detect and wait, never solve (RULE 20).
_SECURITY_SELECTOR = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[title*="challenge" i]'


def _fill(body: str, **payloads: str) -> str:
    """Replace __NAME__ markers with JSON literals (one selector source)."""
    for key, value in payloads.items():
        body = body.replace(f"__{key}__", value)
    return body


# ideal-size: JS literal reason=one executeScript body; splitting the string breaks the Ui.Vision command
_SNAPSHOT = r"""return (function () {
  var previewSels = __PREVIEW__;
  var outSels = __OUTPUTS__;
  var taSel = __TA__;
  var sendSel = __SEND__;
  var spinSel = __SPIN__;
  var secSel = __SEC__;
  var visible = function (el) { return !!(el && el.offsetParent !== null); };
  var first = function (sels) {
    for (var i = 0; i < sels.length; i++) {
      var list = document.querySelectorAll(sels[i]);
      for (var j = 0; j < list.length; j++) if (visible(list[j])) return list[j];
    }
    return null;
  };
  var previews = [];
  previewSels.forEach(function (sel) {
    document.querySelectorAll(sel).forEach(function (el) {
      if (!visible(el)) return;
      previews.push({alt: el.getAttribute('alt') || '', src: el.getAttribute('src') || ''});
    });
  });
  var results = [];
  outSels.forEach(function (sel) {
    document.querySelectorAll(sel).forEach(function (el) {
      if (!visible(el) || !el.src) return;
      var host = el.closest('article, li, div') || el;
      var text = '';
      try { text = (host.innerText || '').slice(0, 500); } catch (e) { text = ''; }
      var job = '';
      var m = text.match(/\[JOB-ID:\s*([^\]]+)\]/);
      if (m) job = m[1].trim();
      results.push({src: el.src, job_id: job, text: text, alt: el.getAttribute('alt') || ''});
    });
  });
  var ta = document.querySelector(taSel);
  var send = document.querySelector(sendSel);
  var spin = document.querySelector(spinSel);
  var sec = document.querySelector(secSel);
  var preview = previews[0] || {alt: '', src: ''};
  return JSON.stringify({
    attachment: {found: previews.length > 0, name: preview.alt, alt: preview.alt,
                 src: preview.src, count: previews.length},
    prompt: ta ? String(ta.value || '') : '',
    send: {found: !!send, enabled: !!(send && !send.disabled && visible(send))},
    security: !!(sec && visible(sec)),
    generating: !!(spin && visible(spin)),
    composer_empty: !!(ta && String(ta.value || '').length === 0),
    page_ready: document.readyState === 'complete' && !!ta,
    results: results
  });
})()"""


def build_snapshot_js() -> str:
    """The read-back probe: attachment, prompt, send, security, results."""
    return _fill(_SNAPSHOT,
                 PREVIEW=json.dumps(attachment_preview_selectors()),
                 OUTPUTS=json.dumps(output_image_selectors()),
                 TA=json.dumps(textarea_primary()),
                 SEND=json.dumps(send_presence_selector()),
                 SPIN=json.dumps(spinner_selector()),
                 SEC=json.dumps(_SECURITY_SELECTOR))


# ideal-size: JS literal reason=one executeScript body; the prompt is a JSON literal so Unicode survives
_INSERT = r"""return (function () {
  var expected = __PROMPT__;
  var el = document.querySelector(__TA__);
  if (!el) return JSON.stringify({ok: false, error: 'textarea not found', actual: ''});
  try {
    var setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(el, expected);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  } catch (e) {
    return JSON.stringify({ok: false, error: String(e), actual: el.value || ''});
  }
  return JSON.stringify({ok: el.value === expected, actual: el.value, len: el.value.length});
})()"""


def build_insert_js(prompt: str) -> str:
    """Chrome's value-setter insert, as a macro script, plus the read-back."""
    return _fill(_INSERT, PROMPT=json.dumps(prompt), TA=json.dumps(textarea_primary()))


# ideal-size: JS literal reason=one executeScript body; bytes return through the savelog echo
_DOWNLOAD = r"""return (async function () {
  var src = __SRC__;
  try {
    var res = await fetch(src, {credentials: 'include'});
    if (!res.ok) return JSON.stringify({started: true, partial: false, error: 'http ' + res.status, b64: '', name: ''});
    var buf = await res.arrayBuffer();
    var bytes = new Uint8Array(buf);
    var head = '';
    try { head = new TextDecoder().decode(bytes.slice(0, 200)).toLowerCase(); } catch (e) { head = ''; }
    if (head.indexOf('<html') >= 0 || head.indexOf('<!doctype') >= 0) {
      return JSON.stringify({started: true, partial: false, error: 'html', b64: '', name: 'page.html'});
    }
    var bin = '';
    for (var i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, Math.min(i + 0x8000, bytes.length)));
    }
    return JSON.stringify({started: true, partial: false, error: '', b64: btoa(bin), name: 'result.bin'});
  } catch (e) {
    return JSON.stringify({started: false, partial: false, error: String(e), b64: '', name: ''});
  }
})()"""


def build_download_js(src: str) -> str:
    """In-page fetch of the correlated result (cookies included) as base64."""
    return _fill(_DOWNLOAD, SRC=json.dumps(src or ""))

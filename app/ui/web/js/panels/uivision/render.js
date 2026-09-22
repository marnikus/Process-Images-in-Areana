/* uivision/render.js — status pill, matched tab line, and the run output.
   Rendering only: no bridge calls, no state. */
'use strict';
const UiVisionRender = {
  _el(id) { return document.getElementById(id); },

  /* The header pill: idle / running / ok / failed. */
  status(state, text) {
    const el = this._el('uivStatus');
    if (!el) return;
    el.textContent = text || state || 'idle';
    el.className = 'uiv-status uiv-' + (state || 'idle');
  },

  /* Which tab the pattern resolved to, or why nothing will run yet. */
  match(payload) {
    const el = this._el('uivMatch');
    if (!el) return;
    const missing = (payload && payload.missing) || [];
    if (missing.length) {
      el.textContent = '⚠ still needed: ' + missing.join(', ');
      el.className = 'uiv-match uiv-warn';
      return;
    }
    const url = (payload && payload.matched_url) || '';
    el.textContent = url ? '▶ macro will open: ' + url : '⚠ no tab matches the pattern';
    el.className = 'uiv-match' + (url ? '' : ' uiv-warn');
  },

  /* The run result: verdict line plus the tail of the Ui.Vision log. */
  outcome(payload) {
    const el = this._el('uivOutput');
    if (!el || !payload) return;
    const lines = payload.lines || [];
    const head = (payload.state || '') + (payload.message ? ' — ' + payload.message : '');
    el.textContent = [head].concat(lines).join('\n');
  },

  /* The macro JSON for the operator to copy into Ui.Vision. */
  macro(text) {
    const el = this._el('uivOutput');
    if (el) el.textContent = text || '';
  },
};
window.UiVisionRender = UiVisionRender;

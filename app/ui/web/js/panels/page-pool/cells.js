/* page-pool/cells.js — the Cooldown cell, ≤120 LOC, CC≤10 (D-4).
   The cell ALWAYS carries a countdown: a live timer outranks every status
   label, a stacked penalty is named a debt, a ready tab reads 00:00. The
   clock is element-anchored (`data-cool-at`) so the 1 s ticker needs no state. */
'use strict';
window.PagePoolCells = {
  _store() { return window.PagePoolStore; },

  _cooldownBadge(p) {
    const captcha = p.captcha_count || 0;
    return captcha > 0 ? ` <span title="Captcha detections on this tab">🛡x${captcha}</span>` : '';
  },

  /* D-4: the cell always carries the countdown — a timer outranks the status
     label, a debt is named a debt, and a ready tab reads 00:00. */
  _clockHtml(p) {
    const s = this._store();
    const remaining = p.cooldown_remaining || 0;
    const total = p.cooldown_total || 0;
    const of = (remaining > 0 && total > 0) ? ` / ${s.fmt(total)}` : '';
    const title = s.esc(p.cooldown_reason || (remaining > 0 ? 'cooling' : 'no active timer'));
    return `<span data-cool-tab="${s.esc(p.tab_id)}" data-cool-left="${remaining}" data-cool-at="${Date.now()}" title="${title}">${s.fmt(remaining)}${of}</span>`;
  },

  _debtHtml(pending) {
    return ` <span title="Stacked penalty — starts cooling when this job ends">+${this._store().fmt(pending)} debt</span>`;
  },

  cooldownCell(p) {
    const pending = p.pending_penalty || 0;
    const clock = this._clockHtml(p) + this._cooldownBadge(p);
    return pending > 0 ? clock + this._debtHtml(pending) : clock;
  },

};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.PagePoolCells = window.PagePoolCells;

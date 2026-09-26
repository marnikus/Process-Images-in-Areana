/* core/jobs-edit.js — click a JOBS count to correct it (I-64, 2026-09-25).
   The count stays a display number, never a routing input (see
   test_job_count_display_only). One delegated listener serves the pool table and
   the URL list, so neither template changes: the tab id comes from the row
   (`tr.dataset.tabId` in the URL list, the `.pool-tab-cell` title in the pool).
   `set_page_jobs` overwrites the live counter AND the stored stat — the store
   merges counters by max, so nothing else can lower one. */
'use strict';
const JobsEdit = {
  CELL: '[title="Jobs completed"]',
  MAX: 999999,

  tabOf(cell) {
    const tr = cell.closest('tr');
    if (!tr) return '';
    const pool = tr.querySelector('.pool-tab-cell');
    return (tr.dataset && tr.dataset.tabId) || (pool && pool.getAttribute('title')) || '';
  },

  parse(val) {
    const text = String(val === undefined || val === null ? '' : val).trim();
    const n = Number(text);
    return text !== '' && Number.isInteger(n) && n >= 0 && n <= this.MAX ? n : null;   // blank ≠ 0
  },

  _ask(current, onOk) {
    if (window.Dialog && window.Dialog.promptEdit) {
      window.Dialog.promptEdit('Jobs completed', String(current), 'Set', onOk);
      return;
    }
    if (typeof prompt !== 'function') return;
    const value = prompt('Jobs completed:', String(current));
    if (value !== null) onOk(value);
  },

  _log(text, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(text, level);  // a lexical global (not window.X)
  },

  send(tabId, val) {
    const n = this.parse(val);
    if (n === null) { this._log(`⚠ Jobs must be a whole number 0-${this.MAX}`, 'warn'); return; }
    const b = window.App && window.App.bridge;
    if (!b || !b.set_page_jobs) return;
    b.set_page_jobs(tabId, n, (res) => this.onReply(tabId, res));
  },

  onReply(tabId, res) {
    let r;
    try { r = JSON.parse(res); } catch (e) { r = { ok: false, error: String(res) }; }
    const label = window.TabLabel ? window.TabLabel.of(tabId) : tabId;
    this._log(r.ok ? `✏ Jobs for ${label} set to ${r.jobs}` : `Jobs edit failed: ${r.error}`,
      r.ok ? 'info' : 'error');
    if (window.PagePoolActions && window.PagePoolActions.refresh) window.PagePoolActions.refresh();
  },

  onClick(ev) {
    const cell = ev.target && ev.target.closest ? ev.target.closest(this.CELL) : null;
    const tabId = cell ? this.tabOf(cell) : '';
    if (!tabId) return;
    this._ask(parseInt(cell.textContent, 10) || 0, (val) => this.send(tabId, val));
  },

  install(doc) {
    if (!doc || !doc.addEventListener || this._installed) return false;
    this._installed = true;
    doc.addEventListener('click', (ev) => this.onClick(ev));
    return true;
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') {
  window.JobsEdit = JobsEdit;
  if (typeof document !== 'undefined') JobsEdit.install(document);
}

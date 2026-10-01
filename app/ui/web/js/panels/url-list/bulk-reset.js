/* url-list/bulk-reset.js — toolbar Reset all cooldowns. */
'use strict';
window.UrlListBulkReset = {
  _busy: false,
  _bridge() { return window.App && window.App.bridge; },
  _store() { return window.UrlListStore || {}; },
  _reply(res) { try { return JSON.parse(res); } catch { return { ok: false, error: 'bad reply' }; } },
  _canReset(page) { return Number(page?.cooldown_remaining || 0) > 0 || Number(page?.pending_penalty || 0) > 0; },
  updateButton(pages) {
    const btn = document.getElementById('urlResetAllCooldownsBtn');
    if (!btn) return false;
    btn.disabled = this._busy || !(pages || []).some(page => this._canReset(page));
    return !btn.disabled;
  },
  run() {
    if (this._busy) return false;
    const b = this._bridge();
    if (!b?.reset_all_url_cooldowns) return false;
    this._busy = true;
    this.updateButton([{ cooldown_remaining: 1 }]);
    b.reset_all_url_cooldowns(res => this._finish(this._reply(res)));
    return true;
  },
  _who(row) { return row.label || row.url || row.tab_id || 'row'; },
  _message(reply, bad) {
    const count = reply.reset_count || 0;
    if (!bad.length) return `Reset all cooldowns: ${count} reset`;
    return `Reset all cooldowns: ${count} reset, ${bad.length} failed (${bad.map(row => this._who(row)).join(', ')})`;
  },
  _finish(reply) {
    this._busy = false;
    this.updateButton(this._store().poolPages || []);
    document.getElementById('urlResetAllCooldownsBtn')?.focus?.();
    const bad = reply.failed_rows || [];
    if (typeof LogConsole !== 'undefined') LogConsole.log(this._message(reply, bad), bad.length || !reply.ok ? 'warn' : 'success');
  },
};

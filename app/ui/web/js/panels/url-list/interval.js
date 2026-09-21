/* url-list/interval.js — URL reconcile interval control (S6/D-12R), ≤70 LOC, CC≤10.

The value travels: input → save_settings({url_reconcile_interval_ms}) (clamped by
Python too) → progress_updated.live.url_interval_ms → this input again. No getter
slot exists (D-20) — the pushed payload is the only read path.
*/
'use strict';
window.UrlInterval = {
  MIN_MS: 500, MAX_MS: 60000, DEFAULT_MS: 5000,

  init() {
    const Boot = window.Boot;
    if (!Boot) return;
    Boot.bindOnceById('urlIntervalSaveBtn', 'click', () => this.save());
    Boot.onBridgeReady(() => this._bindLive());
  },

  clamp(v) {
    let ms = parseInt(v, 10);
    if (isNaN(ms)) ms = this.DEFAULT_MS;
    return Math.max(this.MIN_MS, Math.min(ms, this.MAX_MS));
  },

  applyValue(ms) {
    const input = document.getElementById('urlIntervalMs');
    if (input) input.value = ms;
    return ms;
  },

  load(live) {
    const ms = live && live.url_interval_ms;
    if (ms != null) this.applyValue(this.clamp(ms));
  },

  save() {
    const input = document.getElementById('urlIntervalMs');
    const ms = this.applyValue(this.clamp(input ? input.value : ''));
    const payload = JSON.stringify({ url_reconcile_interval_ms: ms });
    const bridge = this._bridge();
    if (bridge && bridge.save_settings) bridge.save_settings(payload, (res) => this._reply(res, ms));
  },

  _bridge() { return window.App && window.App.bridge; },

  _reply(res, ms) {
    try {
      const r = JSON.parse(res);
      if (typeof LogConsole !== 'undefined') {
        LogConsole.log(r.ok ? `URL reconcile interval saved: ${ms} ms` : `Interval save failed: ${r.error}`,
                       r.ok ? 'success' : 'error');
      }
    } catch (e) { /* malformed bridge reply — the input already shows the clamped value */ }
  },

  _bindLive() {
    const sig = window.progress_updated;
    if (sig && sig.connect) {
      sig.connect((json) => {
        try { this.load((JSON.parse(json) || {}).live); } catch (e) { /* keep stale input */ }
      });
    }
  },
};

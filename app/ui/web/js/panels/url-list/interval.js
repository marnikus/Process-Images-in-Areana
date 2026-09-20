/* url-list/interval.js — the URL reconcile interval control (S6, D-12R), ≤80 LOC, CC≤10.
   Reads the pushed progress_updated.live.url_interval_ms (no getter slot, D-20);
   Save clamps 500…60000 and writes through the existing save_settings slot. */
'use strict';
const UrlInterval = {
  MIN_MS: 500, MAX_MS: 60000, DEFAULT_MS: 5000,
  _liveBound: false,

  init() {
    window.Boot.bindOnceById('urlIntervalSaveBtn', 'click', () => this.save(), 'urlIntervalSave');
    window.Boot.onBridgeReady(() => this._bindLive());
  },

  clamp(v) {
    const n = parseInt(v, 10);
    if (isNaN(n)) return this.DEFAULT_MS;
    return Math.max(this.MIN_MS, Math.min(this.MAX_MS, n));
  },

  applyValue(ms) {
    const el = document.getElementById('urlIntervalMs');
    if (el) el.value = ms;
  },

  load(live) {
    if (!live || live.url_interval_ms === undefined || live.url_interval_ms === null) return;
    this.applyValue(this.clamp(live.url_interval_ms));
  },

  save() {
    const el = document.getElementById('urlIntervalMs');
    const ms = this.clamp(el ? el.value : undefined);
    const call = window.Boot.needBridge('save_settings');
    if (!call) return;
    this.applyValue(ms);
    call(JSON.stringify({ url_reconcile_interval_ms: ms }), (res) => {
      try {
        const r = JSON.parse(res);
        if (typeof LogConsole !== 'undefined') LogConsole.log(r.ok ? `URL reconcile every ${ms} ms` : 'Interval save failed: ' + r.error, r.ok ? 'success' : 'error');
      } catch {}
    });
  },

  _bindLive() {
    const b = window.App && window.App.bridge;
    if (this._liveBound || !b || !b.progress_updated || !b.progress_updated.connect) return;
    this._liveBound = true;
    b.progress_updated.connect((json) => {
      try { this.load(JSON.parse(json).live); } catch {}
    });
  },
};
window.UrlInterval = UrlInterval;

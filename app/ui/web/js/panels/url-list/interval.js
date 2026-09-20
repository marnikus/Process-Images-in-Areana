/* url-list/interval.js — URL reconcile interval control, D-12R */
'use strict';
window.UrlInterval = {
  MIN_MS: 500, MAX_MS: 60000, DEFAULT_MS: 5000,

  clamp(v) {
    const n = parseInt(v, 10);
    if (isNaN(n)) return this.DEFAULT_MS;
    if (n < this.MIN_MS) return this.MIN_MS;
    if (n > this.MAX_MS) return this.MAX_MS;
    return n;
  },

  applyValue(ms) {
    const el = document.getElementById('urlIntervalMs');
    if (el) el.value = String(ms);
  },

  load(live) {
    if (!live || typeof live.url_interval_ms === 'undefined') return;
    const ms = this.clamp(live.url_interval_ms);
    this.applyValue(ms);
  },

  save() {
    const el = document.getElementById('urlIntervalMs');
    const raw = el ? el.value : '';
    const ms = this.clamp(raw);
    this.applyValue(ms);
    const fn = window.Boot ? window.Boot.needBridge('save_settings') : null;
    const call = fn || (window.App && window.App.bridge && window.App.bridge.save_settings);
    if (!call) return;
    try { call(JSON.stringify({url_reconcile_interval_ms: ms}), function(){}); } catch {}
  },

  _bindLive() {
    const b = (window.Boot && window.Boot._bridge && window.Boot._bridge()) || (window.App && window.App.bridge);
    if (!b || !b.progress_updated) return;
    try {
      b.progress_updated.connect((json) => {
        try { const prog = JSON.parse(json); this.load(prog.live || prog); } catch {}
      });
    } catch {}
  },

  init() {
    window.Boot.bindOnceById('urlIntervalSaveBtn', 'click', () => this.save(), 'urlIntervalSaveBtn');
    window.Boot.onBridgeReady(() => this._bindLive());
    // also load from current App.state if already present
    try {
      const live = window.App && window.App.state && window.App.state.progress && window.App.state.progress.live;
      if (live) this.load(live);
    } catch {}
  },
};
if (typeof window !== 'undefined') window.UrlInterval = window.UrlInterval;

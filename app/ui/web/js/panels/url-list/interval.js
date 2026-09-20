/* url-list/interval.js — reconcile cadence control (D-12R), ≤100 LOC, CC≤10 */
'use strict';
const UrlInterval = {
  MIN_MS: 500,
  MAX_MS: 60000,
  DEFAULT_MS: 5000,

  init() {
    window.Boot.bindOnceById('urlIntervalSaveBtn', 'click', () => this.save());
    window.Boot.onBridgeReady((b) => this._bindLive(b));
  },

  _bindLive(b) {
    if (this._liveBound) return;
    if (!b || !b.progress_updated || typeof b.progress_updated.connect !== 'function') return;
    this._liveBound = true;
    b.progress_updated.connect((json) => this._onLive(json));
  },

  _onLive(json) {
    try {
      const live = JSON.parse(json).live;
      if (live && typeof live.url_interval_ms === 'number') this.applyValue(live.url_interval_ms);
    } catch {}
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
    if (live && typeof live.url_interval_ms === 'number') this.applyValue(live.url_interval_ms);
  },

  save() {
    const el = document.getElementById('urlIntervalMs');
    const ms = this.clamp(el ? el.value : NaN);
    const slot = window.Boot.needBridge('save_settings');
    if (slot) slot(JSON.stringify({ url_reconcile_interval_ms: ms }));
  },
};
window.UrlInterval = UrlInterval;

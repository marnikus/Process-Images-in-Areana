/* url-list/interval.js — the "🔁 every … ms" URL reconcile cadence control (S6, D-12R).
   Reads its value from the pushed progress_updated.live payload (no slot round-trip),
   saves through the existing save_settings slot; bounds mirror live/debug_view.py. */
'use strict';
const UrlInterval = {
  MIN: 500, MAX: 60000, DEFAULT: 5000,
  _focused: false,

  init() {
    Boot.bindOnceById('urlIntervalSaveBtn', 'click', () => this.save(), 'urlIntervalSave');
    const input = document.getElementById('urlIntervalMs');
    if (input) {
      Boot.bindOnce(input, 'focus', () => { this._focused = true; }, 'urlIntervalFocus');
      Boot.bindOnce(input, 'blur', () => { this._focused = false; }, 'urlIntervalBlur');
    }
    Boot.onBridgeReady(() => this._bindLive());
  },

  clamp(v) {
    const n = parseInt(v, 10);
    if (isNaN(n)) return this.DEFAULT;
    return Math.max(this.MIN, Math.min(n, this.MAX));
  },

  applyValue(ms) {
    const input = document.getElementById('urlIntervalMs');
    if (input && !this._focused) input.value = String(ms);
  },

  load(live) {
    if (!live || live.url_interval_ms === undefined) return;
    this.applyValue(this.clamp(live.url_interval_ms));
  },

  save() {
    const input = document.getElementById('urlIntervalMs');
    const ms = this.clamp(input ? input.value : this.DEFAULT);
    if (input) input.value = String(ms);
    const call = Boot.needBridge('save_settings');
    if (!call) return;
    call(JSON.stringify({ url_reconcile_interval_ms: ms }), (res) => {
      try {
        const r = JSON.parse(res);
        if (typeof LogConsole !== 'undefined') LogConsole.log(r.ok ? `URL reconcile every ${ms} ms` : 'Interval save failed: ' + r.error, r.ok ? 'success' : 'error');
      } catch {}
    });
  },

  _bindLive() {
    const b = Boot._bridge();
    if (!b || !b.progress_updated || this._live) return;
    this._live = true;
    b.progress_updated.connect((json) => {
      try { this.load(JSON.parse(json).live); } catch {}
    });
  },
};
window.UrlInterval = UrlInterval;

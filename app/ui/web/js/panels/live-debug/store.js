/* live-debug/store.js — the two pushed payloads + a local clock (S9). ≤80 LOC, CC≤10.
   `pool` rides page_pool_updated (workers), `live` rides progress_updated.live (queue +
   cadence). The ticker only recomputes elapsed text locally — never a bridge call. */
'use strict';
window.LiveDebugStore = {
  pool: null,
  live: null,
  now: () => Date.now(),
  _timer: null,

  onPool(payload) {
    this.pool = payload && Array.isArray(payload.pages) ? payload : { total: 0, pages: [] };
    this._paint();
    this._ensureTicker();
  },

  onLive(payload) {
    this.live = payload || null;
    this._paint();
  },

  busyWorkers() {
    const pages = (this.pool && this.pool.pages) || [];
    return pages.filter((p) => p.current_image || /busy|waiting/.test(String(p.status || '')));
  },

  tick() {
    if (this.busyWorkers().length) this._paint();
  },

  _ensureTicker() {
    if (this._timer !== null) return;
    this._timer = setInterval(() => this.tick(), 1000);
  },

  _paint() {
    if (window.LiveDebugRender) window.LiveDebugRender.paint(this);
  },
};

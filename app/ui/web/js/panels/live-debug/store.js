/* live-debug/store.js — the two pushed payloads + a local clock (S9, D-22).
   `live` comes from progress_updated.live, `pool` from page_pool_updated; the
   1 s ticker only re-renders elapsed times — it never calls the bridge. */
'use strict';
window.LiveDebugStore = {
  live: null,
  pool: null,
  _timer: null,
  _onTick: null,

  setLive(live) { if (live && typeof live === 'object') this.live = live; },
  setPool(pool) { if (pool && Array.isArray(pool.pages)) this.pool = pool; },

  nowSec() { return Date.now() / 1000; },

  elapsedSec(since) {
    const s = Number(since) || 0;
    return s > 0 ? Math.max(0, this.nowSec() - s) : 0;
  },

  mmss(totalSecs) {
    const s = Math.max(0, Math.round(totalSecs || 0));
    const m = Math.floor(s / 60);
    return String(m).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  },

  queueHead() {
    const l = this.live || {};
    return { queued: Number(l.queued) || 0, next: String(l.next_image || '') };
  },

  _str(v) { return v == null ? '' : String(v); },

  _workerLine(p) {
    return {
      tabId: this._str(p.tab_id), title: this._str(p.title), status: this._str(p.status),
      connected: p.is_connected !== false, image: this._str(p.current_image), jobId: this._str(p.current_job_id),
      elapsed: this.elapsedSec(p.busy_since), cooldown: Number(p.cooldown_remaining) || 0,
      cooldownReason: this._str(p.cooldown_reason), jobs: Number(p.jobs_completed) || 0,
    };
  },

  workerLines() {
    const pages = (this.pool && this.pool.pages) || [];
    return pages.map((p) => this._workerLine(p));
  },

  startTicker(onTick) {
    this._onTick = onTick;
    if (this._timer) return;
    this._timer = setInterval(() => { if (this._onTick) this._onTick(); }, 1000);
  },
};

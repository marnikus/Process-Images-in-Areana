/* Read-only signal snapshots and local time. ideal-size: one small state owner. */
'use strict';
window.LiveDebugStore = {
  live: null, pool: null, poolAt: 0, liveAt: 0, poolVersion: 0, liveVersion: 0,
  errors: {},

  decode(payload) {
    const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('invalid payload');
    if (data.error) throw new Error(String(data.error));
    return data;
  },

  onPool(payload) {
    try {
      const data = this.decode(payload);
      if (!Array.isArray(data.pages)) throw new Error('invalid worker list');
      if (!data.pages.every(p => p && typeof p.tab_id === 'string')) throw new Error('invalid worker row');
      this.pool = data;
      this.poolAt = Date.now();
      this.poolVersion++;
      delete this.errors.pool;
    } catch (e) { this.errors.pool = `Worker data unavailable: ${e.message} (last snapshot retained)`; }
    this.tick();
  },

  onLive(payload) {
    try {
      const data = this.decode(payload).live;
      if (!data || !Number.isFinite(data.queued)) throw new Error('invalid queue view');
      this.live = data;
      this.liveAt = Date.now();
      this.liveVersion++;
      delete this.errors.live;
    } catch (e) { this.errors.live = `Queue data unavailable: ${e.message} (last snapshot retained)`; }
    this.tick();
  },

  seconds(value) {
    const n = Number(value);
    return Number.isFinite(n) ? Math.max(0, n) : 0;
  },

  age(timestamp) {
    const ms = typeof timestamp === 'string' ? Date.parse(timestamp) : timestamp;
    if (!Number.isFinite(ms) || ms <= 0) return null;
    return Math.max(0, Math.floor((Date.now() - ms) / 1000));
  },

  elapsed(page) {
    return page.current_job_id ? this.age(page.busy_since) : null;
  },

  cooldown(page) {
    const age = this.age(this.poolAt) || 0;
    return Math.max(0, Math.ceil(this.seconds(page.cooldown_remaining) - age));
  },

  tick() { window.LiveDebugRender.render(this); },
};

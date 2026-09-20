/* live-debug/render.js — job-centric lines for the Live Worker & Queue Debug window (S9).
   Deliberately NOT the page-pool table: one line per worker, what it is doing right now. */
'use strict';
window.LiveDebugRender = {
  esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); },

  clock(seconds) {
    const s = Math.max(0, Math.round(seconds));
    return s >= 60 ? `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}` : `${s} s`;
  },

  queueHead(live) {
    if (!live) return 'queue —';
    const r = live.receivers || {};
    const first = live.next_image ? ` · first: ${this.esc(live.next_image)}` : '';
    const wait = live.wait_reason ? ` · waiting: ${this.esc(live.wait_reason)}` : '';
    return `<b>${live.queued | 0} pending</b>${first} · ${r.receivers | 0} of ${r.total | 0} rows can receive` +
      ` · run <span class="ld-muted">${this.esc(live.run_state || 'idle')}</span>${wait}`;
  },

  workerState(p, nowSec) {
    const since = p.busy_since ? nowSec - Number(p.busy_since) : 0;
    const status = String(p.status || '');
    if (status === 'waiting_captcha') return `<span class="ld-captcha">captcha wait ${this.clock(since)} — timeout paused</span>`;
    if (p.current_image) return `<span class="ld-busy">▶ ${this.esc(p.current_image)} · ${this.clock(since)}</span>`;
    if (status === 'cooldown') return `<span class="ld-muted">cooldown ${this.clock(p.cooldown_remaining || 0)}</span>`;
    return `<span class="ld-free">${p.is_connected === false ? 'offline' : 'free'}</span>`;
  },

  worker(p, nowSec) {
    const tab = this.esc(String(p.tab_id || '?').slice(0, 12));
    return `<div class="ld-worker"><span class="ld-tab">${tab}</span><span>${this.esc(p.title || '')}</span>` +
      `${this.workerState(p, nowSec)}<span class="ld-muted">jobs ${p.jobs_completed | 0}</span></div>`;
  },

  workers(pool, nowSec) {
    const pages = (pool && pool.pages) || [];
    if (!pages.length) return '<span class="ld-muted">no connected webpages — link a URL row to a live tab</span>';
    return pages.map((p) => this.worker(p, nowSec)).join('');
  },

  cadence(live, nowSec) {
    if (!live || live.url_interval_ms === undefined) return 'reconcile —';
    const every = (Number(live.url_interval_ms) / 1000).toFixed(1);
    const last = live.last_pass_at ? `last pass ${this.clock(nowSec - Number(live.last_pass_at))} ago` : 'no pass yet';
    return `<span>reconcile every ${every} s</span><span class="ld-muted">${last} · ${live.passes | 0} passes</span>`;
  },

  paint(store) {
    const nowSec = store.now() / 1000;
    const set = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
    set('ldQueueHead', this.queueHead(store.live));
    set('ldWorkers', this.workers(store.pool, nowSec));
    set('ldCadence', this.cadence(store.live, nowSec));
  },
};

/* Job-centric view; no pool-table template or eligibility decision is copied.
   ideal-size: cohesive rendering leaf; strings are escaped at the HTML boundary. */
'use strict';
window.LiveDebugRender = {
  text(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  },

  queueHead(live) {
    if (!live) return 'Waiting for queue status…';
    const head = live.next_image ? `first: ${live.next_image}` : 'queue empty';
    const counts = live.receivers || {};
    return `${live.queued} pending · ${head} · ${counts.receivers ?? 0} receiving · ` +
      `${counts.not_receivers ?? 0} not receiving · run: ${live.run_state || 'idle'}`;
  },

  cadence(store) {
    const live = store.live;
    if (!live) return 'Waiting for reconcile status…';
    const seconds = (store.seconds(live.url_interval_ms) / 1000).toFixed(1);
    const age = store.age(store.seconds(live.last_pass_at) * 1000);
    const last = age === null ? 'not yet run' : `last pass ${age}s ago`;
    return `Reconcile every ${seconds} s · ${last} · ${live.passes ?? 0} passes (read-only)`;
  },

  status(page, scoped) {
    if (!page.is_connected) return 'disconnected';
    const status = String(page.status || 'unknown');
    return !scoped && /captcha/i.test(status) ? 'waiting' : status.replaceAll('_', ' ');
  },

  pause(page, scoped) {
    if (!scoped || page.status !== 'waiting_captcha') return '';
    const p = page.pause;
    if (!p) return 'Captcha wait · pause timing unavailable';
    const s = window.LiveDebugStore;
    const budget = p.remaining_s === null ? 'uncapped' :
      `${s.seconds(p.cap_s)}s cap · ${s.seconds(p.remaining_s)}s remaining`;
    const state = p.remaining_s === 0 ? 'pause cap exhausted' : 'generation timeout paused (up to cap)';
    return `Captcha wait · ${state} · ${s.seconds(p.absorbed_s)}s absorbed · ` +
      `${budget} (last settled; current wait not yet charged)`;
  },

  timing(page, store) {
    const elapsed = store.elapsed(page);
    const parts = [elapsed === null ? 'elapsed unknown' : `elapsed ${elapsed}s`];
    if (page.status === 'cooldown') parts.push(`cooldown ${store.cooldown(page)}s`);
    return parts.join(' · ');
  },

  detail(page, scoped) {
    const detail = String(page.error || page.cooldown_reason || '');
    return !scoped && /captcha|solver/i.test(detail) ? '' : detail;
  },

  worker(page, store) {
    const e = window.UIHelpers.esc;
    const scoped = store.pool.waits_in_scope === true;
    const status = this.status(page, scoped);
    return `<article class="live-debug-worker"><div class="live-debug-worker-head"><strong>${e(page.title || page.tab_id)}</strong>` +
      `<span class="live-debug-worker-status">${e(status)}</span></div>` +
      `<div class="live-debug-identity">${e(page.tab_id)} · ${e(page.url)}</div>` +
      `<div>${e(page.current_job_id || 'No active job')} · ${e(page.current_image || 'no image assigned')}</div>` +
      `<div class="live-debug-timing">${e(this.timing(page, store))} · ${e(page.jobs_completed || 0)} completed</div>` +
      `<div class="live-debug-note">${e(this.detail(page, scoped))}</div>` +
      `<div class="live-debug-pause">${e(this.pause(page, scoped))}</div></article>`;
  },

  workers(store) {
    if (!store.pool) return '<p class="live-debug-empty">Waiting for worker status…</p>';
    if (!store.pool.pages.length) return '<p class="live-debug-empty">No workers connected.</p>';
    return store.pool.pages.map(page => this.worker(page, store)).join('');
  },

  summary(pool) {
    if (!pool) return 'Workers — awaiting snapshot';
    return `${pool.total ?? pool.pages.length} workers · ${pool.busy ?? 0} busy · ` +
      `${pool.cooling ?? 0} cooling · ${pool.free ?? 0} free`;
  },

  render(store) {
    this.text('liveDebugQueue', this.queueHead(store.live));
    this.text('liveDebugCadence', this.cadence(store));
    this.text('liveDebugSummary', this.summary(store.pool));
    this.text('liveDebugStatus', Object.values(store.errors).join(' · '));
    const list = document.getElementById('liveDebugWorkers');
    if (list) list.innerHTML = this.workers(store);
  },
};

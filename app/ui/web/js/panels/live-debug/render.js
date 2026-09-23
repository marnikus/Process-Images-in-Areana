/* live-debug/render.js — string builders for the three strips (S9).
   Job-centric lines (what each worker is doing right now), deliberately not
   the pool's tab-centric table (page-pool/render.js) — no shared template. */
'use strict';
window.LiveDebugRender = {
  _store() { return window.LiveDebugStore; },

  esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },

  queueHead() {
    const q = this._store().queueHead();
    if (!q.queued) return '<b>0 pending</b> · queue empty';
    return `<b>${q.queued} pending</b> · first: ${this.esc(q.next)}`;
  },

  receivers() {
    const r = (this._store().live || {}).receivers || {};
    const total = Number(r.total) || 0;
    if (!total) return 'no URL rows';
    return `<b>${Number(r.receivers) || 0} of ${total}</b> rows can receive a job` + (r.not_receivers ? ` · ${r.not_receivers} ⊘` : '');
  },

  cadence() {
    const st = this._store();
    const l = st.live || {};
    const every = ((Number(l.url_interval_ms) || 0) / 1000).toFixed(1);
    const ago = l.last_pass_at ? `${Math.round(st.elapsedSec(l.last_pass_at))} s ago` : 'never';
    return `reconcile every ${every} s · last pass ${ago} · ${Number(l.passes) || 0} passes · run ${this.esc(l.run_state || 'idle')}`;
  },

  _captchaText(w) {
    const st = this._store();
    const cap = Number((st.live || {}).captcha_cap_sec) || 0;
    return `${this.esc(w.image)} · timeout paused ${st.mmss(w.elapsed)}` + (cap ? ` (cap ${st.mmss(cap)})` : '');
  },

  _idleText(w) {
    const st = this._store();
    if (w.status === 'cooldown') return `cooling ${st.mmss(w.cooldown)}` + (w.cooldownReason ? ` · ${this.esc(w.cooldownReason)}` : '');
    return w.connected ? 'idle · ready' : 'offline';
  },

  _jobText(w) {
    if (w.status === 'waiting_captcha') return this._captchaText(w);
    if (w.image || w.jobId) return `${this.esc(w.image || w.jobId)} · ${this._store().mmss(w.elapsed)}`;
    return this._idleText(w);
  },

  _workerLine(w) {
    const cls = `live-worker live-status-${this.esc(w.status)}`;
    return `<div class="${cls}"><span class="live-no">#${w.no}</span><span class="live-tab" title="${this.esc(w.tabId)}">${this.esc(w.label || w.tabId)}</span>`
      + `<span class="live-state">${this.esc(w.status)}</span><span class="live-job">${this._jobText(w)}</span>`
      + `<span class="live-jobs">${w.jobs} done</span></div>`;
  },

  workers() {
    const lines = this._store().workerLines();
    if (!lines.length) return '<div class="live-debug-empty">no worker tabs — add arena.ai tabs to the pool</div>';
    return lines.map((w) => this._workerLine(w)).join('');
  },
};

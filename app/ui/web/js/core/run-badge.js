/* core/run-badge.js — the run-cycle badge (D-1/D-2).
   Running is the quiet default; PAUSED / STOPPING / STOPPED are loud. This is the
   ONE painter for every `[data-run-badge]` element (Run Controls title, Live Debug
   head), fed by the existing progress_updated.run_state — no slot, no new state. */
'use strict';
const RunBadge = {
  VIEWS: { running: { label: '', mod: '' }, paused: { label: 'PAUSED', mod: 'paused' },
    stopping: { label: 'STOPPING', mod: 'stopping' }, idle: { label: 'STOPPED', mod: 'stopped' } },

  init() { Boot.onBridgeReady(() => this._bindLive()); },

  view(state) { return this.VIEWS[state] || this.VIEWS.idle; },  // unknown reads as stopped: loud, never silent

  apply(state) {
    const v = this.view(state);
    document.querySelectorAll('[data-run-badge]').forEach((el) => {
      el.textContent = v.label;
      el.className = v.mod ? `run-badge run-badge--${v.mod}` : 'run-badge';
      el.hidden = !v.label;
    });
  },

  _bindLive() {
    const b = Boot._bridge();
    if (!b || !b.progress_updated || this._live) return;
    this._live = true;
    b.progress_updated.connect((json) => {
      try { this.apply(JSON.parse(json).run_state); } catch {}
    });
  },
};
window.RunBadge = RunBadge;

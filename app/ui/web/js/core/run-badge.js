/* core/run-badge.js — the run-cycle ON/OFF badge (A-1…A-3, 2026-09-21).
   RUN CYCLE ON for every state but `idle` (paused / cooldown / captcha are still ON);
   RUN CYCLE OFF only after the user stopped it. Never hidden. A sub-label names
   paused / stopping / the live wait reason NEXT TO the badge, never instead of it.
   The ONE painter for every `[data-run-badge]` + `[data-run-sub]` pair, fed by the
   existing progress_updated (run_state + live.wait_reason) — no slot, no new state. */
'use strict';
const RunBadge = {
  ON: { label: 'RUN CYCLE ON', mod: 'on' },
  OFF: { label: 'RUN CYCLE OFF', mod: 'off' },
  STATES: { running: true, paused: true, stopping: true },
  SUBS: { paused: 'paused', stopping: 'stopping after current' },
  REASONS: { 'all cooling': 'waiting for cooldown', 'no tab': 'no usable tab', 'no images': 'queue empty', 'cdp down': 'Chrome disconnected' },

  init() { Boot.onBridgeReady(() => this._bindLive()); },

  view(state) { return this.STATES[state] ? this.ON : this.OFF; },  // unknown reads as OFF: loud, never silent

  sub(state, live) {
    if (!this.STATES[state]) return '';
    if (this.SUBS[state]) return this.SUBS[state];
    return this.REASONS[(live && live.wait_reason) || ''] || '';
  },

  apply(state, live) {
    const v = this.view(state);
    document.querySelectorAll('[data-run-badge]').forEach((el) => {
      el.textContent = v.label;
      el.className = `run-badge run-badge--${v.mod}`;
      el.hidden = false;
    });
    const text = this.sub(state, live);
    document.querySelectorAll('[data-run-sub]').forEach((el) => { el.textContent = text; el.hidden = !text; });
  },

  _bindLive() {
    const b = Boot._bridge();
    if (!b || !b.progress_updated || this._live) return;
    this._live = true;
    b.progress_updated.connect((json) => {
      try { const p = JSON.parse(json); this.apply(p.run_state, p.live); } catch {}
    });
  },
};
window.RunBadge = RunBadge;

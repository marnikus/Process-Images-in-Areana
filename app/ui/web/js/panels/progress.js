/* progress.js — RULE18 file ≤150, CC≤10 via helpers */
'use strict';

const ProgressPanel = {
  init() {},

  restore(state) {
    if (!state) return;
    if (!state.progress) return;
    this.update(state.progress);
  },

  _calcPct(prog) {
    const total = prog.total || 1;
    const done = (prog.completed||0)+(prog.failed||0)+(prog.skipped||0);
    const pct = Math.min(100, Math.round((done/total)*100));
    return pct;
  },

  _updateBar(prog) {
    const bar = document.getElementById('progressBarFill');
    if (!bar) return;
    bar.style.width = this._calcPct(prog)+'%';
  },

  _setText(id, val) {
    const el=document.getElementById(id);
    if (el) el.textContent=val;
  },

  _updateCounts(prog) {
    this._setText('progTotal', prog.total||0);
    this._setText('progPending', prog.pending||0);
    this._setText('progSelected', prog.selected||0);
    this._setText('progProcessing', prog.processing||0);
    this._setText('progCompleted', prog.completed||0);
    this._setText('progFailed', prog.failed||0);
    this._setText('progSkipped', prog.skipped||0);
  },

  _updateStatus(prog) {
    const statusEl = document.getElementById('runStatus');
    if (statusEl) statusEl.textContent = prog.run_state || 'idle';
  },

  update(prog) {
    if (!prog) return;
    this._updateBar(prog);
    this._updateCounts(prog);
    this._updateStatus(prog);
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.ProgressPanel = ProgressPanel;

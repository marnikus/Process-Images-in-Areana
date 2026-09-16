/* progress.js */
'use strict';

const ProgressPanel = {
  init() {
    // nothing
  },

  restore(state) {
    if (!state || !state.progress) return;
    this.update(state.progress);
  },

  update(prog) {
    const bar = document.getElementById('progressBarFill');
    if (bar) {
      const total = prog.total || 1;
      const done = (prog.completed||0)+(prog.failed||0)+(prog.skipped||0);
      const pct = Math.min(100, Math.round((done/total)*100));
      bar.style.width = pct+'%';
    }
    const set = (id, val) => { const el=document.getElementById(id); if(el) el.textContent=val; };
    set('progTotal', prog.total||0);
    set('progPending', prog.pending||0);
    set('progSelected', prog.selected||0);
    set('progProcessing', prog.processing||0);
    set('progCompleted', prog.completed||0);
    set('progFailed', prog.failed||0);
    set('progSkipped', prog.skipped||0);

    const statusEl = document.getElementById('runStatus');
    if (statusEl) statusEl.textContent = prog.run_state || 'idle';
  }
};

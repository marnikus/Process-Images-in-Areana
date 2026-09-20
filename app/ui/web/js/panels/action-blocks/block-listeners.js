/* block-listeners.js — bridge signal registry table (C7)
   Listener registry + dispatch to avoid CC nesting.
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksListeners = {
  /* action_blocks_updated / job_started / job_action_status / job_finished are
     owned by ArenaAppListeners (arena-app/listeners.js) which forwards them to
     the panel with the full Qt argument list. B11: binding them here again
     processed every job event twice (and job_action_status with one arg). */
  _coreEntries(panel) {
    return [
      { signal: 'job_paused', handler: (p) => panel.onJobPaused(p) },
      { signal: 'job_resumed', handler: () => panel.onJobResumed() },
    ];
  },

  _extraEntries(panel) {
    return [
      { signal: 'job_failed', handler: (p) => panel.onJobFailed(p) },
      { signal: 'custom_blocks_updated', handler: () => panel.onCustomBlocksUpdated() },
      { signal: 'stack_presets_updated', handler: () => panel.onStackPresetsUpdated() },
      { signal: 'exported', handler: (p) => panel._io._onExported(p) },
    ];
  },

  buildRegistry(panel) {
    return [...this._coreEntries(panel), ...this._extraEntries(panel)];
  },

  _bindOne(bridge, entry, unsubs) {
    const sig = entry.signal;
    if (bridge[sig] && bridge[sig].connect) {
      try {
        const conn = bridge[sig].connect(entry.handler);
        unsubs.push(() => { try { conn.disconnect(); } catch {} });
      } catch {}
      return;
    }
    if (typeof bridge.on !== 'function') return;
    try {
      bridge.on(sig, entry.handler);
      unsubs.push(() => { try { bridge.off(sig, entry.handler); } catch {} });
    } catch {}
  },

  bindBridge(panel) {
    const bridge = window.App && window.App.bridge;
    if (!bridge) return [];
    const registry = this.buildRegistry(panel);
    const unsubs = [];
    registry.forEach(entry => this._bindOne(bridge, entry, unsubs));
    return unsubs;
  },

  unbindAll(unsubs) {
    (unsubs || []).forEach(fn => { try { fn(); } catch {} });
  },
};

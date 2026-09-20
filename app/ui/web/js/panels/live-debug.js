/* live-debug.js — the Live Worker & Queue Debug window (16th window, S8: registration + shell).
   S9 fills it: queue head, per-worker job lines, receiver counters, all from pushed payloads (D-22). */
'use strict';
const LiveDebugPanel = {
  init() {
    this.el = document.getElementById('winLiveDebug');
  },
};
window.LiveDebugPanel = LiveDebugPanel;

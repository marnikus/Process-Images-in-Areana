/* live-debug.js — Live Worker & Queue Debug panel facade (window 16). S8 registers the
   window; S9 fills it (store / render / actions). Publishes itself (global-name contract). */
'use strict';
const LiveDebugPanel = {
  init() {
    const root = document.getElementById('liveDebugRoot');
    if (root && !root.children.length) root.textContent = 'Live worker & queue view loads in S9.';
  },
};
window.LiveDebugPanel = LiveDebugPanel;

/* live-debug.js — Live Worker & Queue Debug panel facade (window 16, S8/S9).
   Pure observability: merges page_pool_updated (workers) with progress_updated.live
   (queue head + cadence). Self-connects its signals (arena-app/listeners.js is frozen). */
'use strict';
const LiveDebugPanel = {
  _connected: false,

  init() {
    window.Boot.bindOnceById('ldRefreshBtn', 'click', () => this.refresh(), 'liveDebugRefresh');
    window.Boot.onBridgeReady(() => this._connect());
    window.LiveDebugStore.onLive(null);
  },

  onPool(payload) { window.LiveDebugStore.onPool(payload); },
  onLive(payload) { window.LiveDebugStore.onLive(payload); },
  refresh() { return window.LiveDebugActions.refresh(); },

  _connect() {
    const b = window.App && window.App.bridge;
    if (this._connected || !b) return;
    this._connected = true;
    const on = (sig, fn) => { try { b[sig] && b[sig].connect && b[sig].connect(fn); } catch {} };
    on('page_pool_updated', (json) => { try { this.onPool(JSON.parse(json)); } catch {} });
    on('progress_updated', (json) => { try { this.onLive(JSON.parse(json).live); } catch {} });
    this.refresh();
  },
};
window.LiveDebugPanel = LiveDebugPanel;

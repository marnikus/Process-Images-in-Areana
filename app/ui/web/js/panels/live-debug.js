/* live-debug.js — the Live Worker & Queue Debug window (16th window; S8 shell, S9 content).
   Pure observability (D-20/D-22): renders progress_updated.live + page_pool_updated,
   self-connects to both signals (listeners.js stays frozen), ticks elapsed locally. */
'use strict';
const LiveDebugPanel = {
  _connected: false,

  init() {
    Boot.bindOnceById('liveRefreshBtn', 'click', () => this.refresh(), 'liveRefresh');
    Boot.onBridgeReady(() => this._connect());
    window.LiveDebugStore.startTicker(() => this.render());
  },

  _connect() {
    const b = Boot._bridge();
    if (!b || this._connected) return;
    this._connected = true;
    if (b.progress_updated) b.progress_updated.connect((json) => this.onLive(json));
    if (b.page_pool_updated) b.page_pool_updated.connect((json) => this.onPool(json));
  },

  _parse(json) {
    try { return typeof json === 'string' ? JSON.parse(json) : json; } catch { return null; }
  },

  onLive(json) {
    const prog = this._parse(json);
    if (prog && prog.live) { window.LiveDebugStore.setLive(prog.live); this.render(); }
  },

  onPool(json) {
    const snap = this._parse(json);
    if (snap) { window.LiveDebugStore.setPool(snap); this.render(); }
  },

  _set(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  },

  render() {
    const r = window.LiveDebugRender;
    this._set('liveQueueHead', r.queueHead());
    this._set('liveReceivers', r.receivers());
    this._set('liveWorkers', r.workers());
    this._set('liveCadence', r.cadence());
  },

  refresh() { return window.LiveDebugActions.refresh(); },
};
window.LiveDebugPanel = LiveDebugPanel;

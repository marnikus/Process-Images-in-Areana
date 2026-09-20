/* S9 lifecycle facade. ideal-size: only boot/binding; state and views live in parts. */
'use strict';
window.LiveDebugPanel = {
  _initialized: false,
  _timer: null,

  init() {
    if (this._initialized) return;
    this._initialized = true;
    window.Boot.bindOnceById('liveDebugRefreshBtn', 'click', () => this.refresh());
    window.Boot.onBridgeReady(bridge => window.LiveDebugActions.connect(bridge));
    this._timer = setInterval(() => window.LiveDebugStore.tick(), 1000);
    window.LiveDebugStore.tick();
  },

  refresh() { window.LiveDebugActions.refresh(); },
};

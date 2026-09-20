/* Existing read slots only. ideal-size: read/bootstrap orchestration leaf. */
'use strict';
window.LiveDebugActions = {
  read(slot, onReply, onError) {
    const fn = window.Boot.needBridge(slot);
    if (!fn) { onError('bridge unavailable'); return; }
    try { fn(onReply); } catch (e) { onError(e.message); }
  },

  refresh() {
    const store = window.LiveDebugStore, version = store.poolVersion;
    this.read('get_page_pool_status', raw => {
      if (store.poolVersion === version) store.onPool(raw);
    }, error => store.onPool({ error }));
  },

  loadQueue() {
    const store = window.LiveDebugStore, version = store.liveVersion;
    this.read('get_arena_state', raw => {
      if (store.liveVersion !== version) return;
      try { store.onLive(store.decode(raw).progress); }
      catch (e) { store.onLive({error: e.message}); }
    }, error => store.onLive({error}));
  },

  connect(bridge) {
    if (!bridge) return;
    bridge.page_pool_updated.connect(raw => window.LiveDebugStore.onPool(raw));
    bridge.progress_updated.connect(raw => window.LiveDebugStore.onLive(raw));
    this.loadQueue();
    this.refresh();
  },
};

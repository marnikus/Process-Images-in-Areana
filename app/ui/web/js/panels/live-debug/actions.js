/* live-debug/actions.js — the one bridge read of the window (S9): Refresh re-reads the pool.
   No writes: the reconcile interval is owned by the URL List bar (D-12R). */
'use strict';
window.LiveDebugActions = {
  refresh() {
    const call = window.Boot.needBridge('get_page_pool_status');
    if (!call) return false;
    call((res) => {
      try { window.LiveDebugStore.onPool(JSON.parse(res)); } catch {}
    });
    return true;
  },
};

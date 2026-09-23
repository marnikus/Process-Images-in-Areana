/* live-debug/actions.js — the only bridge traffic of the window (S9).
   One read (`get_page_pool_status`, whose reply also rides page_pool_updated);
   no writes — the cadence control lives in the URL List bar (D-12R). */
'use strict';
window.LiveDebugActions = {
  refresh() {
    const call = Boot.needBridge('get_page_pool_status');
    if (!call) return false;
    call((res) => {
      try { window.LiveDebugPanel.onPool(res); } catch {}
    });
    return true;
  },
};

/* cdp/cdp-listeners.js — bridge listeners & tab handling (C7) */
'use strict';
window.CDPListeners = {
  bindBridgeSignals(panel) {
    const bridge = window.App && window.App.bridge;
    if (!bridge) return;
    try {
      if (bridge.url_presets_updated) bridge.url_presets_updated.connect((p) => panel.renderBookmarks(p));
    } catch (e) { console.warn('CDP bind failed', e); }
  },

  _logTabsReceived(store) {
    if (store.tabs.length === 0) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Received 0 tabs', 'warn');
      return;
    }
    const real = store.getRealTabs(store.tabs);
    const devCount = store.tabs.length - real.length;
    if (typeof LogConsole === 'undefined') return;
    if (devCount > 0) LogConsole.log(`📑 Received ${store.tabs.length} tab(s) (${real.length} real + ${devCount} devtools)`, 'success');
    else LogConsole.log(`📑 Received ${store.tabs.length} unique Chrome tab(s)`, 'success');
  },

  _isDebouncedAuto(only, store, now) {
    const sameAuto = only.ws_url === store._lastAutoConnectWs && (now - store._lastAutoConnectTs) < 5000;
    const sameConn = only.ws_url === store._lastConnectWs && (now - store._lastConnectTs) < 5000;
    return sameAuto || sameConn;
  },

  _autoConnectIfSingle(store) {
    const real = store.getRealTabs(store.tabs);
    if (real.length !== 1) return;
    const only = real[0];
    const now = Date.now();
    if (this._isDebouncedAuto(only, store, now)) return;
    const sel = document.getElementById('tabSelect');
    if (sel) { sel.value = only.ws_url; store.selectedWs = only.ws_url; }
    store._lastAutoConnectWs = only.ws_url;
    store._lastAutoConnectTs = now;
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.connect_tab) bridge.connect_tab(only.ws_url);
  },

  onTabsReceived(panel, payload) {
    try {
      if (payload === 'pending') return;
      const tabs = JSON.parse(payload);
      const store = window.CDPStore;
      store.tabs = store.dedupTabs(tabs);
      panel.renderTabSelect(store.tabs);
      this._logTabsReceived(store);
      this._autoConnectIfSingle(store);
      panel.updateUrlRowsConnection();
    } catch (e) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('Failed to parse tabs: ' + e, 'error');
    }
  },

  onConnectionStatus(panel, status) {
    const dot = document.getElementById('connectionStatus');
    if (dot) {
      dot.className = 'status-dot ' + (status === 'connected' ? 'connected' : status === 'error' ? 'error' : 'disconnected');
      dot.title = status;
    }
    const store = window.CDPStore;
    if (status === 'connected') store.connected = true;
    if (status === 'disconnected') store.connected = false;
    if (typeof LogConsole !== 'undefined') {
      if (status === 'connected') LogConsole.log('✅ Chrome connected', 'success');
      if (status === 'disconnected') LogConsole.log('🔌 Chrome disconnected', 'warn');
      if (status === 'error') LogConsole.log('❌ Chrome connection error', 'error');
    }
    panel.updateUrlRowsConnection();
  },

  _handleNoMatches(query, store) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(`❌ No Chrome tab matches “${query}”`, 'error');
    if (store.tabs.length === 0) setTimeout(() => { if (window.CDPActions) window.CDPActions.diagnose(); }, 500);
  },

  _isDebouncedBest(best, store) {
    const now = Date.now();
    return best.ws_url === store._lastAutoConnectWs && (now - store._lastAutoConnectTs) < 1500;
  },

  _connectBestMatch(best, store, panel) {
    const sel = document.getElementById('tabSelect');
    if (sel) { sel.value = best.ws_url; store.selectedWs = best.ws_url; }
    if (this._isDebouncedBest(best, store)) { panel.updateUrlRowsConnection(); return false; }
    store._lastAutoConnectWs = best.ws_url;
    store._lastAutoConnectTs = Date.now();
    return true;
  },

  _doConnectBest(best) {
    const bridge = window.App && window.App.bridge;
    if (!bridge || !bridge.connect_tab) return;
    if (typeof LogConsole !== 'undefined') LogConsole.log(`🔗 Auto-connecting to ${best.title}`, 'info');
    bridge.connect_tab(best.ws_url);
  },

  onTabMatchResult(panel, query, payload) {
    try {
      const matches = JSON.parse(payload);
      const store = window.CDPStore;
      if (!matches || !matches.length) { this._handleNoMatches(query, store); return; }
      const best = matches[0];
      if (typeof LogConsole !== 'undefined') LogConsole.log(`🎯 Best match (${best.kind}, ${best.score}): ${best.title}`, 'success');
      if (!this._connectBestMatch(best, store, panel)) return;
      this._doConnectBest(best);
      panel.updateUrlRowsConnection();
    } catch (e) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('Tab match parse failed: ' + e, 'error');
    }
  },
};

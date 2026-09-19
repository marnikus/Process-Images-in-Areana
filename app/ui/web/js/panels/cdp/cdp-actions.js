/* cdp/cdp-actions.js — bridge actions for CDP (C7) */
'use strict';
window.CDPActions = {
  _bridge() { return window.App && window.App.bridge; },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
  },

  fetchTabs() {
    const store = window.CDPStore;
    const cfg = store.currentConfig || { host: '127.0.0.1', port: 9222 };
    this._log(`🔍 Fetching Chrome tabs from http://${cfg.host}:${cfg.port}/json/list …`, 'info');
    const bridge = this._bridge();
    if (!bridge || !bridge.get_tabs) { this._log('Bridge not ready for tabs', 'warn'); return; }
    try {
      bridge.get_tabs((res) => {
        if (!res || res === 'pending') return;
        try {
          const tabs = JSON.parse(res);
          if (Array.isArray(tabs) && window.CDPPanel) window.CDPPanel.onTabsReceived(res);
        } catch {}
      });
    } catch (e) { this._log('get_tabs failed: ' + e, 'error'); }
  },

  _handleDiagnoseResult(res) {
    if (!res || res === 'pending') { this._log('⏳ Diagnose running in background…', 'info'); return; }
    try {
      const diag = JSON.parse(res);
      this._log(diag.summary || 'Diagnose done', diag.summary && diag.summary.includes('✅') ? 'success' : 'warn');
      if (diag.tabs && diag.tabs.length && window.CDPPanel) window.CDPPanel.onTabsReceived(JSON.stringify(diag.tabs));
    } catch (e) { this._log('Diagnose parse failed: ' + e, 'error'); }
  },

  diagnose() {
    const store = window.CDPStore;
    const cfg = store.currentConfig || { host: '127.0.0.1', port: 9222 };
    this._log(`🩺 Diagnosing Chrome on ${cfg.host}:${cfg.port}…`, 'info');
    const bridge = this._bridge();
    if (!bridge || !bridge.diagnose_chrome) { this._log('diagnose_chrome not available', 'error'); return; }
    try {
      bridge.diagnose_chrome((res) => this._handleDiagnoseResult(res));
    } catch (e) { this._log('diagnose_chrome call failed: ' + e, 'error'); }
  },

  _shouldDebounceConnect(ws) {
    const store = window.CDPStore;
    const now = Date.now();
    return ws === store._lastConnectWs && (now - store._lastConnectTs) < 1500;
  },

  connectSelected() {
    const store = window.CDPStore;
    const sel = document.getElementById('tabSelect');
    const ws = sel ? sel.value : store.selectedWs;
    if (!ws) { this._log('⚠ No tab selected', 'warn'); return; }
    if (this._shouldDebounceConnect(ws)) return;
    store._lastConnectWs = ws;
    store._lastConnectTs = Date.now();
    this._log('🔗 Connecting to ' + ws.slice(0, 60) + '…', 'info');
    const bridge = this._bridge();
    if (bridge && bridge.connect_tab) bridge.connect_tab(ws);
  },

  autoConnectBookmark() {
    const store = window.CDPStore;
    const input = document.getElementById('urlBookmarkInput');
    let query = (input ? input.value.trim() : '').trim();
    if (!query) { this._log('⚠ Bookmark field empty', 'warn'); return; }
    query = store._extractUrl(query);
    this._log(`🔍 Auto-connect: finding tab for “${query}” …`, 'info');
    store.lastMatchQuery = query;
    const bridge = this._bridge();
    if (bridge && bridge.find_tab_by_url) bridge.find_tab_by_url(query);
    if (bridge && bridge.set_last_url_preset) bridge.set_last_url_preset(query);
  },

  _tryLoadBookmarksAsync(bridge) {
    try {
      bridge.get_url_presets((res) => {
        try { if (typeof res === 'string' && window.CDPPanel) window.CDPPanel.renderBookmarks(res); } catch {}
      });
      return true;
    } catch { return false; }
  },

  _tryLoadBookmarksSync(bridge) {
    try {
      const res = bridge.get_url_presets();
      if (typeof res === 'string' && window.CDPPanel) window.CDPPanel.renderBookmarks(res);
    } catch {}
  },

  loadBookmarks() {
    const bridge = this._bridge();
    if (!bridge || !bridge.get_url_presets) return;
    if (!this._tryLoadBookmarksAsync(bridge)) this._tryLoadBookmarksSync(bridge);
  },

  addBookmark() {
    const input = document.getElementById('urlBookmarkInput');
    const url = input ? input.value.trim() : '';
    if (!url) return;
    const bridge = this._bridge();
    if (bridge && bridge.add_url_preset) bridge.add_url_preset(url);
  },

  removeBookmark(url) {
    const bridge = this._bridge();
    if (bridge && bridge.remove_url_preset) bridge.remove_url_preset(url);
  },

  autoConnectScan() {
    const bridge = this._bridge();
    if (bridge && bridge.auto_connect_scan) bridge.auto_connect_scan('auto');
  },

  manualReparse() {
    this._log('🔄 Reparse requested', 'info');
    const bridge = this._bridge();
    if (bridge && bridge.auto_connect_scan) bridge.auto_connect_scan('manual');
  },

  ensurePrimary() {
    const bridge = this._bridge();
    if (bridge && bridge.ensure_primary_connected) bridge.ensure_primary_connected();
  },
};

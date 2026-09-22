/* cdp.js — facade (C7)
   Delegates to cdp-store, cdp-render, cdp-actions, cdp-listeners
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

const CDPPanel = {
  _store: null,
  _render: null,
  _actions: null,
  _listeners: null,
  _diagnoseBtn: null,

  get tabs() { return this._store.tabs; },
  set tabs(v) { this._store.tabs = v; },
  get connected() { return this._store.connected; },
  set connected(v) { this._store.connected = v; },
  get selectedWs() { return this._store.selectedWs; },
  set selectedWs(v) { this._store.selectedWs = v; },
  get currentConfig() { return this._store.currentConfig; },
  set currentConfig(v) { this._store.currentConfig = v; },

  init() {
    this._store = window.CDPStore;
    this._render = window.CDPRender;
    this._actions = window.CDPActions;
    this._listeners = window.CDPListeners;
    this.bindUI();
    this.bindBridgeSignals();
    setTimeout(() => this.fetchTabs(), 800);
    setTimeout(() => this.loadBookmarks(), 900);
    setTimeout(() => this.autoConnectScan(), 4000);
    setInterval(() => this.ensurePrimary(), 500);
  },

  bindUI() {
    this._bindDiagnoseButton();
    this._bindTabButtons();
    this._bindBookmarkInputs();
  },

  _bindDiagnoseButton() {
    const connectBtn = document.getElementById('connectBtn');
    if (connectBtn && !document.getElementById('diagnoseChromeBtn')) {
      const diagBtn = document.createElement('button');
      diagBtn.id = 'diagnoseChromeBtn';
      diagBtn.className = 'btn-small';
      diagBtn.innerHTML = '<span class="material-icons" style="font-size:16px;">bug_report</span> Diagnose';
      connectBtn.parentNode.insertBefore(diagBtn, connectBtn.nextSibling);
      this._diagnoseBtn = diagBtn;
      diagBtn.addEventListener('click', () => this.diagnose());
    } else {
      this._diagnoseBtn = document.getElementById('diagnoseChromeBtn');
      if (this._diagnoseBtn) this._diagnoseBtn.addEventListener('click', () => this.diagnose());
    }
    const helpBtn = document.getElementById('chromeHelpBtn');
    if (helpBtn) helpBtn.addEventListener('click', () => this.showHelp());
  },

  _bindTabButtons() {
    const refreshBtn = document.getElementById('refreshTabsBtn');
    const connectBtn = document.getElementById('connectBtn');
    const tabSelect = document.getElementById('tabSelect');
    const reparseBtn = document.getElementById('reparseTabsBtn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => this.fetchTabs());
    if (reparseBtn) reparseBtn.addEventListener('click', () => this.manualReparse());
    if (connectBtn) connectBtn.addEventListener('click', () => this.connectSelected());
    if (tabSelect) tabSelect.addEventListener('change', (e) => { this.selectedWs = e.target.value; });
  },

  _bindBookmarkInputs() {
    const bookmarkInput = document.getElementById('urlBookmarkInput');
    const bookmarkConnectBtn = document.getElementById('urlBookmarkConnectBtn');
    const addBookmarkBtn = document.getElementById('addUrlBookmarkBtn');
    if (bookmarkInput) bookmarkInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.autoConnectBookmark(); });
    if (bookmarkConnectBtn) bookmarkConnectBtn.addEventListener('click', () => this.autoConnectBookmark());
    if (addBookmarkBtn) addBookmarkBtn.addEventListener('click', () => this.addBookmark());
  },

  showHelp() {
    const msg = `How to start Chrome for Arena:\n1) Close ALL Chrome windows\n2) Run: start-arena-chrome.bat\n3) In THAT window open https://arena.ai\n4) Click Diagnose, Refresh tabs, Connect`;
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, 'info');
    alert(msg);
  },

  bindBridgeSignals() { this._listeners.bindBridgeSignals(this); },
  fetchTabs() { this._actions.fetchTabs(); },
  diagnose() { this._actions.diagnose(); },
  connectSelected() { this._actions.connectSelected(); },
  autoConnectBookmark() { this._actions.autoConnectBookmark(); },
  loadBookmarks() { this._actions.loadBookmarks(); },
  addBookmark() { this._actions.addBookmark(); },
  removeBookmark(url) { this._actions.removeBookmark(url); },
  autoConnectScan() { this._actions.autoConnectScan(); },
  manualReparse() { this._actions.manualReparse(); },
  ensurePrimary() { this._actions.ensurePrimary(); },

  isDevTab(t) { return this._store.isDevTab(t); },
  getRealTabs(tabs) { return this._store.getRealTabs(tabs); },
  findBestTabForUrl(url) { return this._store.findBestTabForUrl(url); },
  _extractUrl(q) { return this._store._extractUrl(q); },

  onTabsReceived(payload) { this._listeners.onTabsReceived(this, payload); },
  onConnectionStatus(status) { this._listeners.onConnectionStatus(this, status); },
  onTabMatchResult(query, payload) { this._listeners.onTabMatchResult(this, query, payload); },

  renderTabSelect(tabs) {
    const sel = document.getElementById('tabSelect');
    const prev = sel ? sel.value : '';
    this._render.renderTabSelect(tabs, prev);
    const bmInput = document.getElementById('urlBookmarkInput');
    if (bmInput && bmInput.value.trim()) this.highlightMatchingTabs(bmInput.value.trim());
  },

  renderBookmarks(payload) {
    this._render.renderBookmarks(payload, (url) => {
      const inp = document.getElementById('urlBookmarkInput');
      if (inp) inp.value = url;
      this.autoConnectBookmark();
    }, (url) => this.removeBookmark(url));
  },

  updateChromeToolbar(cfg) {
    this._store.currentConfig = cfg;
    this._render.updateChromeToolbar(cfg);
  },

  highlightMatchingTabs(query) { this._render.highlightMatchingTabs(this._store, query); },
  updateUrlRowsConnection() { this._render.updateUrlRowsConnection(this._store); },
  esc(s) { return this._render.esc(s); },
};

if (typeof window !== 'undefined') window.CDPPanel = CDPPanel;

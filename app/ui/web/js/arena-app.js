/* arena-app.js — Main App facade (C13/C15)
   Delegates to arena-app/listeners registry table
   RULE18: file 150-300 ideal, func ≤30, CC≤10
*/
'use strict';

const App = {
  bridge: null,
  ready: false,
  state: null,
  gridLoaded: false,
  globalHistory: [],
  globalHistoryIndex: -1,
  UNDO_KINDS: ['grid', 'urls', 'folder', 'queue', 'prompt', 'settings', 'window_states', 'arena'],
};

App.recordGlobal = function(kind, value, options) {
  if (typeof ArenaHistory !== 'undefined' && ArenaHistory.recordGlobal) {
    return ArenaHistory.recordGlobal(kind, value, options);
  }
  if (this.bridge?.push_global_history && !(options?.localOnly)) {
    try { this.bridge.push_global_history(kind, JSON.stringify(value)); } catch(e){}
  }
};

const _PANEL_INITS = [
  'WindowPresets','UrlList','FolderPicker','ImageQueue','PromptEditor',
  'RunControls','ProgressPanel','WatcherPanel','PagePoolPanel','SettingsPanel',
  'CaptchaPanel','CaptchaRecordingsPanel','BrowserPreview','HighlightOverlay',
  'CDPPanel','ArenaPresets','ActionBlocksPanel'
];

function _initIfExists(name) {
  const obj = window[name];
  if (obj?.init) obj.init();
}

function initApp() {
  setupHeader();
  _PANEL_INITS.forEach(_initIfExists);
  document.getElementById('clearLogBtn')?.addEventListener('click', () => LogConsole.clear());
  if (App.bridge) initWithBridge();
}

function _setupTheme() {
  const themeBtn = document.getElementById('themeToggleBtn');
  if (!themeBtn) return;
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('arena.theme', next);
    if (App.bridge?.set_theme) App.bridge.set_theme(next);
  });
  const saved = localStorage.getItem('arena.theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
}

function _setupUndoRedo() {
  const undoBtn = document.getElementById('undoBtn');
  const redoBtn = document.getElementById('redoBtn');
  if (undoBtn) undoBtn.addEventListener('click', () => { if (typeof ArenaHistory !== 'undefined') ArenaHistory.undoGlobal(); });
  if (redoBtn) redoBtn.addEventListener('click', () => { if (typeof ArenaHistory !== 'undefined') ArenaHistory.redoGlobal(); });
}

function _onKeydown(e) {
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  const k = e.key.toLowerCase();
  if (k === 'z' && !e.shiftKey) {
    e.preventDefault();
    if (typeof ArenaHistory !== 'undefined') ArenaHistory.undoGlobal();
  } else if (k === 'y' || (k === 'z' && e.shiftKey)) {
    e.preventDefault();
    if (typeof ArenaHistory !== 'undefined') ArenaHistory.redoGlobal();
  }
}

function setupHeader() {
  _setupTheme();
  _setupUndoRedo();
  document.addEventListener('keydown', _onKeydown);
}

function _loadGrid() {
  if (typeof SashGrid !== 'undefined' && SashGrid._loadFromBackend) SashGrid._loadFromBackend();
  if (typeof WindowPresets !== 'undefined') WindowPresets.refresh();
}

function _loadUndoHistory() {
  if (!App.bridge?.get_undo_history) return;
  App.bridge.get_undo_history((json) => {
    try {
      const data = JSON.parse(json);
      if (typeof ArenaHistory !== 'undefined') {
        ArenaHistory.loadGlobalHistory(data);
        ArenaHistory._syncGlobalHistory();
      }
    } catch (e) {}
  });
}

function _restoreArenaPanels(data) {
  const panels = ['UrlList','FolderPicker','ImageQueue','PromptEditor','ProgressPanel','SettingsPanel'];
  panels.forEach(name => {
    const obj = window[name];
    if (obj?.restore) obj.restore(data);
  });
}

function _loadArenaState() {
  if (!App.bridge?.get_arena_state) return;
  App.bridge.get_arena_state((json) => {
    try {
      const data = JSON.parse(json);
      App.state = data;
      _restoreArenaPanels(data);
    } catch (e) { console.error('Failed to parse arena_state', e); }
  });
}

function _loadAppState() {
  if (!App.bridge?.get_app_state) return;
  App.bridge.get_app_state((json) => {
    try { restoreSession(JSON.parse(json)); } catch (e) { console.error('Failed to parse app_state', e); }
  });
}

function initWithBridge() {
  setupBridgeListeners();
  _loadGrid();
  _loadUndoHistory();
  _loadAppState();
  _loadArenaState();
}

function restoreSession(data) {
  if (!data) return;
  if (data.theme) {
    document.documentElement.setAttribute('data-theme', data.theme);
    localStorage.setItem('arena.theme', data.theme);
  }
  if (typeof LogConsole !== 'undefined') LogConsole.log('Session restored', 'info');
}

function setupBridgeListeners() {
  const b = App.bridge;
  if (!b) return;
  if (window.ArenaAppListeners) window.ArenaAppListeners.bindBridge(b);
}

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready((bridge) => {
    if (bridge) { App.bridge = bridge; App.ready = true; }
    initApp();
  });

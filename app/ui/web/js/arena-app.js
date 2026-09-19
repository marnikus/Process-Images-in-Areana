/* arena-app.js — Main App facade (C13)
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
  if (this.bridge && this.bridge.push_global_history && !(options && options.localOnly)) {
    try { this.bridge.push_global_history(kind, JSON.stringify(value)); } catch(e){}
  }
};

function initApp() {
  setupHeader();
  if (typeof WindowPresets !== 'undefined') WindowPresets.init();
  if (typeof UrlList !== 'undefined') UrlList.init();
  if (typeof FolderPicker !== 'undefined') FolderPicker.init();
  if (typeof ImageQueue !== 'undefined') ImageQueue.init();
  if (typeof PromptEditor !== 'undefined') PromptEditor.init();
  if (typeof RunControls !== 'undefined') RunControls.init();
  if (typeof ProgressPanel !== 'undefined') ProgressPanel.init();
  if (typeof WatcherPanel !== 'undefined') WatcherPanel.init();
  if (typeof PagePoolPanel !== 'undefined') PagePoolPanel.init();
  if (typeof SettingsPanel !== 'undefined') SettingsPanel.init();
  if (typeof CaptchaPanel !== 'undefined') CaptchaPanel.init();
  if (typeof CaptchaRecordingsPanel !== 'undefined') CaptchaRecordingsPanel.init();
  if (typeof BrowserPreview !== 'undefined') BrowserPreview.init();
  if (typeof HighlightOverlay !== 'undefined') HighlightOverlay.init();
  if (typeof CDPPanel !== 'undefined') CDPPanel.init();
  if (typeof ArenaPresets !== 'undefined') ArenaPresets.init();
  if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.init();
  document.getElementById('clearLogBtn')?.addEventListener('click', () => LogConsole.clear());
  if (App.bridge) initWithBridge();
}

function setupHeader() {
  const themeBtn = document.getElementById('themeToggleBtn');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const cur = document.documentElement.getAttribute('data-theme') || 'dark';
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('arena.theme', next);
      if (App.bridge && App.bridge.set_theme) App.bridge.set_theme(next);
    });
    const saved = localStorage.getItem('arena.theme') || 'dark';
    document.documentElement.setAttribute('data-theme', saved);
  }
  const undoBtn = document.getElementById('undoBtn');
  const redoBtn = document.getElementById('redoBtn');
  if (undoBtn) undoBtn.addEventListener('click', () => { if (typeof ArenaHistory !== 'undefined') ArenaHistory.undoGlobal(); });
  if (redoBtn) redoBtn.addEventListener('click', () => { if (typeof ArenaHistory !== 'undefined') ArenaHistory.redoGlobal(); });
  document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;
    if (!mod) return;
    if (e.key.toLowerCase() === 'z' && !e.shiftKey) {
      e.preventDefault();
      if (typeof ArenaHistory !== 'undefined') ArenaHistory.undoGlobal();
    } else if ((e.key.toLowerCase() === 'y') || (e.key.toLowerCase() === 'z' && e.shiftKey)) {
      e.preventDefault();
      if (typeof ArenaHistory !== 'undefined') ArenaHistory.redoGlobal();
    }
  });
}

function initWithBridge() {
  setupBridgeListeners();
  if (typeof SashGrid !== 'undefined' && SashGrid._loadFromBackend) SashGrid._loadFromBackend();
  if (typeof WindowPresets !== 'undefined') WindowPresets.refresh();
  if (App.bridge.get_undo_history) {
    App.bridge.get_undo_history((json) => {
      try {
        const data = JSON.parse(json);
        if (typeof ArenaHistory !== 'undefined') ArenaHistory.loadGlobalHistory(data);
        if (typeof ArenaHistory !== 'undefined') ArenaHistory._syncGlobalHistory();
      } catch (e) {}
    });
  }
  if (App.bridge.get_app_state) {
    App.bridge.get_app_state((json) => {
      try { restoreSession(JSON.parse(json)); } catch (e) { console.error('Failed to parse app_state', e); }
    });
  }
  if (App.bridge.get_arena_state) {
    App.bridge.get_arena_state((json) => {
      try {
        const data = JSON.parse(json);
        App.state = data;
        if (typeof UrlList !== 'undefined' && UrlList.restore) UrlList.restore(data);
        if (typeof FolderPicker !== 'undefined' && FolderPicker.restore) FolderPicker.restore(data);
        if (typeof ImageQueue !== 'undefined' && ImageQueue.restore) ImageQueue.restore(data);
        if (typeof PromptEditor !== 'undefined' && PromptEditor.restore) PromptEditor.restore(data);
        if (typeof ProgressPanel !== 'undefined' && ProgressPanel.restore) ProgressPanel.restore(data);
        if (typeof SettingsPanel !== 'undefined' && SettingsPanel.restore) SettingsPanel.restore(data);
      } catch (e) { console.error('Failed to parse arena_state', e); }
    });
  }
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
  if (window.ArenaAppListeners) {
    window.ArenaAppListeners.bindBridge(b);
  }
}

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready((bridge) => {
    if (bridge) { App.bridge = bridge; App.ready = true; }
    initApp();
  });

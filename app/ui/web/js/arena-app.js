/* arena-app.js — Main App facade for Arena Image Processor
   Owns bridge, state, boot sequence.
*/
'use strict';

const App = {
  bridge: null,
  ready: false,
  state: null, // arena state from backend
  gridLoaded: false,
};

function initApp() {
  // Header wiring
  setupHeader();

  // Init panels (DOM only)
  if (typeof WindowPresets !== 'undefined') WindowPresets.init();
  if (typeof UrlList !== 'undefined') UrlList.init();
  if (typeof FolderPicker !== 'undefined') FolderPicker.init();
  if (typeof ImageQueue !== 'undefined') ImageQueue.init();
  if (typeof PromptEditor !== 'undefined') PromptEditor.init();
  if (typeof RunControls !== 'undefined') RunControls.init();
  if (typeof ProgressPanel !== 'undefined') ProgressPanel.init();
  if (typeof SettingsPanel !== 'undefined') SettingsPanel.init();
  if (typeof BrowserPreview !== 'undefined') BrowserPreview.init();
  if (typeof HighlightOverlay !== 'undefined') HighlightOverlay.init();

  document.getElementById('clearLogBtn')?.addEventListener('click', () => LogConsole.clear());

  if (App.bridge) initWithBridge();
}

function setupHeader() {
  // theme toggle already in old app-bridge; keep simple
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
}

function initWithBridge() {
  setupBridgeListeners();

  // sash-grid may have initialized before bridge; load authoritative copy
  if (typeof SashGrid !== 'undefined' && SashGrid._loadFromBackend) {
    SashGrid._loadFromBackend();
  }

  if (typeof WindowPresets !== 'undefined') WindowPresets.refresh();

  // Load full app state
  if (App.bridge.get_app_state) {
    App.bridge.get_app_state((json) => {
      try {
        const data = JSON.parse(json);
        restoreSession(data);
      } catch (e) {
        console.error('Failed to parse app_state', e);
      }
    });
  }

  // Load arena state
  if (App.bridge.get_arena_state) {
    App.bridge.get_arena_state((json) => {
      try {
        const data = JSON.parse(json);
        App.state = data;
        // Dispatch to panels
        if (typeof UrlList !== 'undefined' && UrlList.restore) UrlList.restore(data);
        if (typeof FolderPicker !== 'undefined' && FolderPicker.restore) FolderPicker.restore(data);
        if (typeof ImageQueue !== 'undefined' && ImageQueue.restore) ImageQueue.restore(data);
        if (typeof PromptEditor !== 'undefined' && PromptEditor.restore) PromptEditor.restore(data);
        if (typeof ProgressPanel !== 'undefined' && ProgressPanel.restore) ProgressPanel.restore(data);
        if (typeof SettingsPanel !== 'undefined' && SettingsPanel.restore) SettingsPanel.restore(data);
      } catch (e) {
        console.error('Failed to parse arena_state', e);
      }
    });
  }
}

function restoreSession(data) {
  if (!data) return;
  // theme
  if (data.theme) {
    document.documentElement.setAttribute('data-theme', data.theme);
    localStorage.setItem('arena.theme', data.theme);
  }
  // grid_layout and window_states handled by sash-grid via bridge
  // nothing else needed here for now
  if (typeof LogConsole !== 'undefined') {
    LogConsole.log('Session restored', 'info');
  }
}

function setupBridgeListeners() {
  const b = App.bridge;
  if (!b) return;

  // log_message
  if (b.log_message) {
    b.log_message.connect((msg, level) => {
      if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
    });
  }

  // arena specific signals
  if (b.arena_log) {
    b.arena_log.connect((msg, level) => {
      if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
    });
  }
  if (b.arena_state_updated) {
    b.arena_state_updated.connect((json) => {
      try {
        const data = JSON.parse(json);
        App.state = data;
        if (typeof UrlList !== 'undefined' && UrlList.restore) UrlList.restore(data);
        if (typeof ImageQueue !== 'undefined' && ImageQueue.restore) ImageQueue.restore(data);
        if (typeof ProgressPanel !== 'undefined' && ProgressPanel.restore) ProgressPanel.restore(data);
      } catch (e) {}
    });
  }
  if (b.progress_updated) {
    b.progress_updated.connect((json) => {
      try {
        const prog = JSON.parse(json);
        if (typeof ProgressPanel !== 'undefined' && ProgressPanel.update) ProgressPanel.update(prog);
      } catch (e) {}
    });
  }
  if (b.highlight_rect) {
    b.highlight_rect.connect((json) => {
      try {
        const rect = JSON.parse(json);
        if (typeof HighlightOverlay !== 'undefined') HighlightOverlay.show(rect);
      } catch (e) {}
    });
  }
  if (b.grid_layout_changed) {
    b.grid_layout_changed.connect((payload) => {
      // SashGrid already handles via _loadFromBackend? Just log
      console.log('grid_layout_changed', payload?.slice?.(0,100));
    });
  }
  if (b.window_preset_list_updated) {
    b.window_preset_list_updated.connect((json) => {
      if (typeof WindowPresets !== 'undefined' && WindowPresets.onListUpdated) {
        WindowPresets.onListUpdated(json);
      }
    });
  }
}

// boot
(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready((bridge) => {
    if (bridge) {
      App.bridge = bridge;
      App.ready = true;
    }
    initApp();
  });

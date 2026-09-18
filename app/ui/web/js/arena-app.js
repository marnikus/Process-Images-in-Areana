/* arena-app.js — Main App facade for Arena Image Processor
   Owns bridge, state, boot sequence.
*/
'use strict';

const App = {
  bridge: null,
  ready: false,
  state: null, // arena state from backend
  gridLoaded: false,
  globalHistory: [],
  globalHistoryIndex: -1,
  UNDO_KINDS: ['grid', 'urls', 'folder', 'queue', 'prompt', 'settings', 'window_states', 'arena'],
};

// compatibility: App.recordGlobal used by sash-grid.js
App.recordGlobal = function(kind, value, options) {
  if (typeof ArenaHistory !== 'undefined' && ArenaHistory.recordGlobal) {
    return ArenaHistory.recordGlobal(kind, value, options);
  }
  // fallback: directly push if bridge available
  if (this.bridge && this.bridge.push_global_history && !(options && options.localOnly)) {
    try { this.bridge.push_global_history(kind, JSON.stringify(value)); } catch(e){}
  }
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
  if (typeof WatcherPanel !== 'undefined') WatcherPanel.init();
  if (typeof PagePoolPanel !== 'undefined') PagePoolPanel.init();
  if (typeof SettingsPanel !== 'undefined') SettingsPanel.init();
  if (typeof CaptchaPanel !== 'undefined') CaptchaPanel.init();
  if (typeof CaptchaRecordingsPanel !== 'undefined') CaptchaRecordingsPanel.init();
  if (typeof BrowserPreview !== 'undefined') BrowserPreview.init();
  if (typeof HighlightOverlay !== 'undefined') HighlightOverlay.init();
  if (typeof CDPPanel !== 'undefined') CDPPanel.init();
  if (typeof ArenaPresets !== 'undefined') ArenaPresets.init();
  if (typeof RecordingsPanel !== 'undefined') RecordingsPanel.init();
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
  // undo/redo buttons
  const undoBtn = document.getElementById('undoBtn');
  const redoBtn = document.getElementById('redoBtn');
  if (undoBtn) undoBtn.addEventListener('click', () => {
    if (typeof ArenaHistory !== 'undefined') ArenaHistory.undoGlobal();
  });
  if (redoBtn) redoBtn.addEventListener('click', () => {
    if (typeof ArenaHistory !== 'undefined') ArenaHistory.redoGlobal();
  });
  // keyboard shortcuts Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z
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

  // sash-grid may have initialized before bridge; load authoritative copy
  if (typeof SashGrid !== 'undefined' && SashGrid._loadFromBackend) {
    SashGrid._loadFromBackend();
  }

  if (typeof WindowPresets !== 'undefined') WindowPresets.refresh();

  // Load undo history first
  if (App.bridge.get_undo_history) {
    App.bridge.get_undo_history((json) => {
      try {
        const data = JSON.parse(json);
        if (typeof ArenaHistory !== 'undefined') ArenaHistory.loadGlobalHistory(data);
        // sync local mirror
        if (typeof ArenaHistory !== 'undefined') ArenaHistory._syncGlobalHistory();
      } catch (e) {}
    });
  }

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

  // Dedup: only listen to arena_log, ignore log_message to prevent double logs
  // (Python _log previously emitted both signals; now emits only arena_log)
  // If bridge only has log_message, use it; otherwise prefer arena_log
  const hasArenaLog = !!b.arena_log;
  if (!hasArenaLog && b.log_message) {
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
  // Debounce arena_state_updated to avoid freeze on rapid batch updates
  let _arenaStateTimer = null;
  let _pendingArenaState = null;
  if (b.arena_state_updated) {
    b.arena_state_updated.connect((json) => {
      try {
        _pendingArenaState = json;
        if (_arenaStateTimer) return; // already scheduled
        _arenaStateTimer = setTimeout(() => {
          _arenaStateTimer = null;
          const j = _pendingArenaState;
          _pendingArenaState = null;
          if (!j) return;
          try {
            const data = JSON.parse(j);
            App.state = data;
            if (typeof UrlList !== 'undefined' && UrlList.restore) UrlList.restore(data);
            if (typeof ImageQueue !== 'undefined' && ImageQueue.restore) ImageQueue.restore(data);
            if (typeof ProgressPanel !== 'undefined' && ProgressPanel.restore) ProgressPanel.restore(data);
          } catch (e) {}
        }, 250); // 250ms debounce
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
      // Disabled per user request: visual rect should draw only on webpage via CDP, not in App
      // Previously called HighlightOverlay.show(rect) which drew in app overlay — now no-op
      try {
        const rect = JSON.parse(json);
        // Optionally log for debugging but do not draw in app
        // if (typeof LogConsole !== 'undefined') LogConsole.log(`🔍 Highlight (webpage only): ${rect.label||''} at ${rect.x},${rect.y}`, 'info');
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
  if (b.history_changed) {
    b.history_changed.connect(() => {
      if (typeof ArenaHistory !== 'undefined') ArenaHistory._syncGlobalHistory();
    });
  }
  if (b.undo_state_changed) {
    b.undo_state_changed.connect((json) => {
      if (typeof ArenaHistory !== 'undefined') ArenaHistory.onUndoStateChanged(json);
    });
  }
  // CDP
  if (b.tabs_received) {
    b.tabs_received.connect((payload) => {
      if (typeof CDPPanel !== 'undefined') CDPPanel.onTabsReceived(payload);
    });
  }
  if (b.connection_status) {
    b.connection_status.connect((status) => {
      if (typeof CDPPanel !== 'undefined') CDPPanel.onConnectionStatus(status);
      if (typeof PagePoolPanel !== 'undefined' && status === 'connected') {
        setTimeout(()=>PagePoolPanel.refresh(), 800);
      }
    });
  }
  if (b.tab_match_result) {
    b.tab_match_result.connect((query, payload) => {
      if (typeof CDPPanel !== 'undefined') CDPPanel.onTabMatchResult(query, payload);
    });
  }
  if (b.url_presets_updated) {
    b.url_presets_updated.connect((payload) => {
      if (typeof CDPPanel !== 'undefined') CDPPanel.renderBookmarks(payload);
    });
  }
  if (b.presets_changed) {
    b.presets_changed.connect((kind, payload) => {
      if (kind === 'arena' && typeof ArenaPresets !== 'undefined') ArenaPresets.renderArenaPresets(payload);
      if (kind === 'urls' && typeof CDPPanel !== 'undefined') CDPPanel.renderBookmarks(payload);
    });
  }
  // Action Blocks — stacking jobs
  if (b.action_blocks_updated) {
    b.action_blocks_updated.connect((payload) => {
      if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onBlocksUpdated(payload);
    });
  }
  if (b.job_action_status) {
    b.job_action_status.connect((jobId, blockId, statusJson) => {
      if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onJobActionStatus(jobId, blockId, statusJson);
    });
  }
  if (b.job_started) {
    b.job_started.connect((jobId, imagePath) => {
      if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onJobStarted(jobId, imagePath);
    });
  }
  if (b.job_finished) {
    b.job_finished.connect((jobId, resultJson) => {
      if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onJobFinished(jobId, resultJson);
    });
  }
  // Watcher — generation & captcha passive monitoring
  if (b.watcher_status) {
    b.watcher_status.connect((payload) => {
      if (typeof WatcherPanel !== 'undefined') WatcherPanel.onStatusUpdate(payload);
    });
  }
  if (b.watcher_log) {
    b.watcher_log.connect((msg, level) => {
      if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
    });
  }
  // PagePool — multi-page steady/busy
  if (b.page_pool_updated) {
    b.page_pool_updated.connect((payload) => {
      if (typeof PagePoolPanel !== 'undefined') PagePoolPanel.onUpdate(payload);
      if (typeof UrlList !== 'undefined' && UrlList.onPoolUpdate) UrlList.onPoolUpdate(payload);
    });
  }
  // Thumbnails — non-blocking to avoid freeze
  if (b.thumbnail_ready) {
    b.thumbnail_ready.connect((imgId, payload) => {
      if (typeof ImageQueue !== 'undefined' && ImageQueue.onThumbnailReady) {
        ImageQueue.onThumbnailReady(imgId, payload);
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

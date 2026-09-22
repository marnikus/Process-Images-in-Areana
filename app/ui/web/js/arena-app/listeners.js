/* arena-app/listeners.js — C13 split: bridge listeners registry table
   RULE18: file 150-300, func ≤30, CC≤10 via helpers
*/
'use strict';

window.ArenaAppListeners = {
  _arenaStateTimer: null,
  _pendingArenaState: null,
  // Panels re-rendered from every live `arena_state_updated` push, in order.
  LIVE_STATE_PANELS: ['UrlList', 'ImageQueue', 'ProgressPanel'],
  _applyErrors: new Set(),

  _handleArenaLog(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
  },

  /* B10: a live-state render failure is never silent and never takes the
     other panels down with it (one throwing restore() used to skip the Image
     Queue + Progress refresh inside a single bare try/catch). */
  _reportApplyError(name, e) {
    const msg = (e && e.message) ? e.message : String(e);
    console.error(`[App] live state: ${name} failed`, e);
    if (this._applyErrors.has(name)) return;
    this._applyErrors.add(name);
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`UI state sync: ${name} failed to render (${msg}) — other panels keep updating`, 'error');
    }
  },

  _restorePanel(name, data) {
    const panel = window[name];
    if (!panel || typeof panel.restore !== 'function') return false;
    try { panel.restore(data); return true; } catch (e) { this._reportApplyError(name, e); return false; }
  },

  _applyPendingState(j) {
    if (!j) return;
    let data;
    try { data = JSON.parse(j); } catch (e) { this._reportApplyError('state payload', e); return; }
    if (!data || typeof data !== 'object') return;
    window.App.state = data;
    this.LIVE_STATE_PANELS.forEach((name) => this._restorePanel(name, data));
  },

  _handleArenaState(json) {
    try {
      this._pendingArenaState = json;
      if (this._arenaStateTimer) return;
      this._arenaStateTimer = setTimeout(() => {
        this._arenaStateTimer = null;
        const j = this._pendingArenaState;
        this._pendingArenaState = null;
        this._applyPendingState(j);
      }, 250);
    } catch (e) {}
  },

  _handleProgress(json) {
    try {
      const prog = JSON.parse(json);
      if (typeof ProgressPanel !== 'undefined' && ProgressPanel.update) ProgressPanel.update(prog);
    } catch (e) {}
  },

  _handleHighlight(json) {
    try { JSON.parse(json); } catch (e) {}
  },

  _handleGridLayout(payload) {
    console.log('grid_layout_changed', payload?.slice?.(0,100));
  },

  _handleWindowPresetList(json) {
    if (typeof WindowPresets !== 'undefined' && WindowPresets.onListUpdated) WindowPresets.onListUpdated(json);
  },

  _handleHistoryChanged() {
    if (typeof ArenaHistory !== 'undefined') ArenaHistory._syncGlobalHistory();
  },

  _handleUndoState(json) {
    if (typeof ArenaHistory !== 'undefined') ArenaHistory.onUndoStateChanged(json);
  },

  _handleTabsReceived(payload) {
    if (typeof CDPPanel !== 'undefined') CDPPanel.onTabsReceived(payload);
  },

  _handleConnectionStatus(status, browser) {
    if (typeof CDPPanel !== 'undefined') CDPPanel.onConnectionStatus(status, browser);
    if (typeof PagePoolPanel !== 'undefined' && status === 'connected') setTimeout(()=>PagePoolPanel.refresh(), 800);
  },

  _handleTabMatch(query, payload) {
    if (typeof CDPPanel !== 'undefined') CDPPanel.onTabMatchResult(query, payload);
  },

  _handleUrlPresets(payload) {
    if (typeof CDPPanel !== 'undefined') CDPPanel.renderBookmarks(payload);
  },

  _handlePresetsChanged(kind, payload) {
    if (kind === 'arena' && typeof ArenaPresets !== 'undefined') ArenaPresets.renderArenaPresets(payload);
    if (kind === 'urls' && typeof CDPPanel !== 'undefined') CDPPanel.renderBookmarks(payload);
  },

  _handleActionBlocks(payload) {
    if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onBlocksUpdated(payload);
  },

  _handleJobActionStatus(jobId, blockId, statusJson) {
    if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onJobActionStatus(jobId, blockId, statusJson);
  },

  /* B10: per-job row updates go straight to the Image Queue (processing →
     completed/failed) — no dependence on the debounced full-state push. */
  _handleJobStarted(jobId, imagePath) {
    if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onJobStarted(jobId);
    const q = window.ImageQueue;
    if (q && q.onJobStarted) { try { q.onJobStarted(jobId, imagePath); } catch (e) { this._reportApplyError('ImageQueue.onJobStarted', e); } }
  },

  _handleJobFinished(jobId, resultJson) {
    if (typeof ActionBlocksPanel !== 'undefined') ActionBlocksPanel.onJobFinished(jobId, resultJson);
    const q = window.ImageQueue;
    if (q && q.onJobFinished) { try { q.onJobFinished(jobId, resultJson); } catch (e) { this._reportApplyError('ImageQueue.onJobFinished', e); } }
  },

  _handleWatcherStatus(payload) {
    if (typeof WatcherPanel !== 'undefined') WatcherPanel.onStatusUpdate(payload);
  },

  _handleWatcherLog(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
  },

  _handleCaptchaWatcherStatus(payload) {
    if (typeof CaptchaPanel !== 'undefined' && CaptchaPanel.onStatusUpdate) CaptchaPanel.onStatusUpdate(payload);
  },

  _handlePagePool(payload) {
    if (typeof PagePoolPanel !== 'undefined') PagePoolPanel.onUpdate(payload);
    if (typeof UrlList !== 'undefined' && UrlList.onPoolUpdate) UrlList.onPoolUpdate(payload);
  },

  _handleThumbnail(imgId, payload) {
    if (typeof ImageQueue !== 'undefined' && ImageQueue.onThumbnailReady) ImageQueue.onThumbnailReady(imgId, payload);
  },

  buildRegistry() {
    return {
      arena_log: (msg, level) => this._handleArenaLog(msg, level),
      arena_state_updated: (json) => this._handleArenaState(json),
      progress_updated: (json) => this._handleProgress(json),
      highlight_rect: (json) => this._handleHighlight(json),
      grid_layout_changed: (payload) => this._handleGridLayout(payload),
      window_preset_list_updated: (json) => this._handleWindowPresetList(json),
      history_changed: () => this._handleHistoryChanged(),
      undo_state_changed: (json) => this._handleUndoState(json),
      tabs_received: (payload) => this._handleTabsReceived(payload),
      connection_status: (status) => this._handleConnectionStatus(status),
      tab_match_result: (q, p) => this._handleTabMatch(q, p),
      url_presets_updated: (payload) => this._handleUrlPresets(payload),
      presets_changed: (k, p) => this._handlePresetsChanged(k, p),
      action_blocks_updated: (payload) => this._handleActionBlocks(payload),
      job_action_status: (j, b, s) => this._handleJobActionStatus(j, b, s),
      job_started: (j, p) => this._handleJobStarted(j, p),
      job_finished: (j, r) => this._handleJobFinished(j, r),
      watcher_status: (p) => this._handleWatcherStatus(p),
      watcher_log: (m, l) => this._handleWatcherLog(m, l),
      captcha_watcher_status: (p) => this._handleCaptchaWatcherStatus(p),
      page_pool_updated: (p) => this._handlePagePool(p),
      thumbnail_ready: (id, p) => this._handleThumbnail(id, p),
    };
  },

  bindBridge(bridge) {
    const registry = this.buildRegistry();
    Object.keys(registry).forEach(signal => {
      if (bridge[signal]) {
        try { bridge[signal].connect(registry[signal]); } catch (e) {}
      }
    });
    const hasArenaLog = !!bridge.arena_log;
    if (!hasArenaLog && bridge.log_message) {
      bridge.log_message.connect((msg, level) => {
        if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level);
      });
    }
  },
};

if (typeof window !== 'undefined') window.ArenaAppListeners = window.ArenaAppListeners;

/**
 * panels/workspace/flow.js — what the buttons DO.
 *
 * Save / Browse / Load last / preview / Restore, plus the RULE 24 live sync a
 * restore has to perform: restored values must reach the LIVE UI, not just the
 * files (2026-09-25 owner directive — "no visible value may wait for a restart").
 * Every step updates the status line, and every failure is shown, never silent.
 *
 * Sliced from `panels/workspace.js` (audit #3 L9).
 */
'use strict';

let wsBridge = null;   // bound bridge (set by the mount)

function wsSaveWorkspace(baseDir) {
  const name = (wsEl.wsName?.value || '').trim() || 'workspace';
  wsStatusText('saving…');
  const opts = JSON.stringify({ name, description: wsEl.wsDescription?.value || '',
    base_dir: baseDir || '' });
  _call('save_workspace', opts).then((raw) => {
    const reply = wsParse(raw);
    if (!reply.ok) {
      wsStatusText('save failed');
      wsRenderResult({ title: 'Save failed', rows: [reply.error || 'unknown error'] });
      return;
    }
    wsStatusText('saved');
    wsRenderResult(wsSaveSummary(reply));
    wsRefresh();
  });
}

function wsBrowseAndPreview(mode) {
  _call('browse_workspace_folder', mode).then((raw) => {
    const reply = wsParse(raw);
    if (!reply.ok) { if (!reply.cancelled) wsStatusText('browse failed'); return; }
    wsLoadPreview(reply.path);
  });
}

function wsLoadLast(onReady) {
  _call('get_workspace_state').then((raw) => {
    const state = wsParse(raw);
    const last = state.last_snapshot;
    if (!last) {
      wsStatusText('no snapshot yet');
      if (onReady) onReady('');        // the caller decides what "nothing" means
      return;
    }
    wsLoadPreview(last, () => { if (onReady) onReady(last); });
  });
}

function wsLoadPreview(root, onReady) {
  wsStatusText('reading…');
  _call('preview_workspace', root).then((raw) => {
    const reply = wsParse(raw);
    if (!reply.ok) {
      wsStatusText('not a snapshot');
      wsRenderResult({ title: 'Cannot restore', rows: [reply.error || 'unknown'] });
      return;
    }
    wsSetPreview(reply);
    wsRenderPreview(reply);
    wsStatusText('preview');
    if (onReady) onReady();
  });
}

function wsRefresh() {
  _call('get_workspace_state').then((raw) => {
    if (!raw) return;
    const state = wsParse(raw);
    wsRenderRecent(state.recent || [], state.last_snapshot || '');
  });
}

function wsRestore(selected) {
  if (wsPendingPreview()) { wsRunRestore(wsPendingPreview().root, selected); return; }
  // no pending preview: load the LAST snapshot and restore it — never silent
  wsStatusText('loading last snapshot…');
  wsLoadLast((last) => {
    if (!last) {
      wsStatusText('nothing to restore');
      wsRenderResult({ title: 'Nothing to restore',
        rows: ['No snapshot yet — save a workspace or Browse… to one first.'] });
      return;
    }
    wsRunRestore(last, selected);
  });
}

function wsRunRestore(root, selected) {
  wsStatusText('restoring…');
  _call('restore_workspace', root, JSON.stringify({ selected })).then((raw) => {
    const reply = wsParse(raw);
    wsStatusText(reply.ok === true ? 'restored' : 'restore failed');
    wsRenderResult(wsRestoreSummary(reply));
    wsHidePreview();
    wsAfterRestore(reply);
    wsRefresh();
  });
}

function wsAfterRestore(reply) {
  const restored = reply.restored || [];
  if (restored.indexOf('arena_state') >= 0) wsPushRestoredState();
  if (restored.indexOf('grid_window') >= 0) wsApplyRestoredGrid();
  if (restored.indexOf('session_settings') >= 0 || restored.indexOf('cooldowns') >= 0) {
    wsReloadConfigPanels();
  }
  wsRefreshLists(restored);
}

// ---- RULE 24 live sync: the restored values must reach the LIVE UI ---------

// Panels re-rendered from the fresh arena payload after a restore.
const WS_LIVE_PANELS = ['UrlList', 'ImageQueue', 'ProgressPanel', 'SettingsPanel',
  'PromptEditor', 'FolderPicker'];

// Config-driven panels render boot-time pulls — a restore must re-run their
// loaders or every field they own stays stale until restart (RULE 24).
const WS_CONFIG_RELOADERS = [
  ['UrlList', 'loadCooldownConfig'], ['JobCycleSetting', 'load'],
  ['SettingsPanel', 'loadCDPConfig'],
  ['WatcherPanel', 'loadConfig'],
  ['FirefoxAutoPanel', 'load'],
  ['ActionBlocksPanel', 'load'],
];

function wsPushRestoredState() {
  _call('get_arena_state').then((raw) => {
    const state = wsParse(raw);
    if (!state || typeof state !== 'object' || state.ok === false) return;
    if (typeof App !== 'undefined') App.state = state;
    for (const name of WS_LIVE_PANELS) {
      const panel = window[name];
      if (!panel || typeof panel.restore !== 'function') continue;
      try { panel.restore(state); } catch (e) { console.error(`[WorkspacePanel] ${name}`, e); }
    }
  });
}

function wsApplyRestoredGrid() {
  _call('get_grid_layout').then((raw) => {
    const payload = wsParse(raw);
    if (!payload || !payload.tree) return;
    _call('get_window_states').then((statesRaw) => {
      const states = wsParse(statesRaw) || {};
      wsApplyGridTree(payload, states);
    });
  });
}

function wsGridDeserialize(payload) {
  const res = SashCore.deserialize(JSON.stringify({ v: payload.v, tree: payload.tree }));
  if (res && res.ok) return res;
  if (typeof LogConsole !== 'undefined') {
    LogConsole.log('♻️ Restored grid not applied: ' + (res ? res.error : 'no deserializer'), 'warn');
  }
  return null;
}

function wsApplyGridTree(payload, states) {
  if (typeof SashCore === 'undefined' || typeof SashGrid === 'undefined') return;
  const res = wsGridDeserialize(payload);
  if (!res) return;
  SashGrid.root = res.tree;                       // same core path as a window preset
  SashGrid.closedWindows = new Set(states.closed || []);
  SashGrid.minimizedWindows = new Set(states.minimized || []);
  if (SashGrid._restoreWinElsVisibility) SashGrid._restoreWinElsVisibility();
  SashGrid.render();
  if (SashGrid._save) SashGrid._save();
  if (SashGrid._saveWindowStates) SashGrid._saveWindowStates();
  if (typeof LogConsole !== 'undefined') LogConsole.log('♻️ Restored grid layout applied', 'success');
}

function wsReloadConfigPanels() {
  for (const [name, method] of WS_CONFIG_RELOADERS) {
    try { window[name]?.[method]?.(); }
    catch (e) { console.error(`[WorkspacePanel] ${name}.${method}`, e); }
  }
}

function wsRefreshLists(restored) {
  if (restored.indexOf('window_presets') >= 0 && window.WindowPresets?.refresh) {
    window.WindowPresets.refresh();
  }
  if (restored.indexOf('captcha_stats') >= 0 && window.CaptchaPanel?.refresh) {
    window.CaptchaPanel.refresh();
  }
}

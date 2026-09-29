/**
 * panels/workspace-live-sync.js — RULE 24 live refresh after a workspace restore.
 *
 * Second half of the "Global Saving System" window, split from workspace.js
 * (RULE 18.2 file sizing; both stay flat classic scripts sharing globals).
 * After a restore reply, every panel that renders a stored value re-loads from
 * the restored stores in the same tick — files and stores alone leave the UI
 * showing pre-restore values ("visible after restart" is a bug). New live
 * consumers of restored values MUST join WS_LIVE_PANELS / WS_CONFIG_RELOADERS
 * (design doc §M).
 */
'use strict';

// Restored values must reach the LIVE UI, not just the files (RULE 24:
// 2026-09-25 owner directive — no visible value may wait for an app restart).
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

function wsAfterRestore(reply) {
  const restored = reply.restored || [];
  if (restored.indexOf('arena_state') >= 0) wsPushRestoredState();
  if (restored.indexOf('grid_window') >= 0) wsApplyRestoredGrid();
  if (restored.indexOf('session_settings') >= 0 || restored.indexOf('cooldowns') >= 0) {
    wsReloadConfigPanels();
  }
  wsRefreshLists(restored);
}

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

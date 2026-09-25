/**
 * panels/workspace.js — the "Global Saving System" window (19th window, I-51).
 *
 * Part 1 (mount): winWorkspace is registered in every registry (Python catalog,
 * constants.js, store.js winElIds, _PANEL_INITS) — never an L-5 orphan.
 * Part 2 (flow): Save Workspace… / Save As… / Browse… / Load last / preview with
 * per-domain checklist → Restore All or Restore Selected → result with
 * Restored / Skipped / Migrated counts, per-file warnings (stage + cause +
 * recommended action), Open-folder and Copy-details affordances. All bridge
 * traffic goes through one `_call` helper; every failure is shown, never silent.
 *
 * Flat top-level functions (no module IIFE): every function stays inside the
 * RULE 16 hard limits (≤30 LOC, CC ≤10) on its own.
 */
'use strict';

const wsEl = {};          // grabbed once per init(): wsStatus, wsSaveBtn, …
let wsBridge = null;      // bound bridge (Boot._bridge() at init time)
let wsPreview = null;     // the manifest-only preview for the pending restore

const WS_IDS = ['wsStatus', 'wsName', 'wsDescription', 'wsSaveBtn', 'wsSaveAsBtn',
  'wsBrowseBtn', 'wsLoadLastBtn', 'wsPreview', 'wsRestoreActions',
  'wsRestoreAllBtn', 'wsRestoreSelectedBtn', 'wsCancelPreviewBtn',
  'wsRecentList', 'wsResult'];

function wsStatusText(text) {
  if (wsEl.wsStatus) wsEl.wsStatus.textContent = text;
}

function wsEsc(text) {
  // regex escaper (no DOM round-trip): the headless test harness's fake DOM
  // does not emulate textContent→innerHTML, and this is auditable anyway
  return String(text == null ? '' : text).replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[ch]));
}

function wsParse(raw) {
  try { return JSON.parse(raw || '{}'); } catch (e) { return { ok: false, error: 'bad reply' }; }
}

function _call(name, ...args) {
  // QWebChannel slots reply through a trailing callback the caller passes —
  // without it the return value is silently dropped (the classic dead-slot
  // bug). Boot.needBridge = the slot bound to the bridge, or null + ONE
  // warning — never silent.
  const fn = (typeof Boot !== 'undefined') ? Boot.needBridge(name)
    : (wsBridge && typeof wsBridge[name] === 'function' ? wsBridge[name].bind(wsBridge) : null);
  if (!fn) return Promise.resolve(null);
  return new Promise((resolve) => {
    try { fn(...args, (raw) => resolve(raw)); }
    catch (e) { console.error(`[WorkspacePanel] ${name} failed`, e); resolve(null); }
  });
}

function wsRefresh() {
  _call('get_workspace_state').then((raw) => {
    if (!raw) return;
    const state = wsParse(raw);
    wsRenderRecent(state.recent || [], state.last_snapshot || '');
  });
}

function wsRenderRecent(recent, last) {
  if (!wsEl.wsRecentList) return;
  if (!recent.length) { wsEl.wsRecentList.innerHTML = 'none yet'; return; }
  const rows = recent.map((path) => {
    const mark = path === last ? ' ⏱ last' : '';
    const open = `<a href="#" data-open="${wsEsc(path)}" style="color:var(--accent)">open</a>`;
    return `<div>• ${wsEsc(path.split(/[\\/]/).pop())}${mark} ${open}</div>`;
  });
  wsEl.wsRecentList.innerHTML = rows.join('');
}

function wsSaveSummary(reply) {
  const excluded = (reply.domains || []).filter((d) => d.excluded);
  const rows = [`Snapshot: ${reply.path || ''}`,
    `Result: ${reply.result} — ${(reply.domains || []).length} domains`];
  for (const item of excluded) rows.push(`excluded: ${item.domain_id}`);
  for (const err of reply.errors || []) rows.push(`${err.domain_id}: ${err.cause}`);
  return { title: 'Workspace saved', rows, openPath: reply.path };
}

function wsRenderResult(summary) {
  if (!wsEl.wsResult) return;
  wsEl.wsResult.style.display = '';
  const rows = summary.rows.map((r) => `<div>${wsEsc(r)}</div>`).join('');
  const open = summary.openPath
    ? `<button class="btn" data-open="${wsEsc(summary.openPath)}">Open folder</button> ` : '';
  const copy = `<button class="btn" id="wsCopyBtn">Copy details</button>`;
  wsEl.wsResult.innerHTML = `<b>${wsEsc(summary.title)}</b><br>${rows}` +
    `<div style="margin-top:6px;">${open}${copy}</div>`;
  wsBindCopy(summary);
}

function wsBindCopy(summary) {
  const copyBtn = document.getElementById('wsCopyBtn');
  if (!copyBtn) return;
  copyBtn.addEventListener('click', () => {
    const text = summary.raw ? JSON.stringify(summary.raw, null, 2) : summary.rows.join('\n');
    if (navigator.clipboard) navigator.clipboard.writeText(text);
  });
}

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

function wsLoadLast() {
  _call('get_workspace_state').then((raw) => {
    const state = wsParse(raw);
    if (!state.last_snapshot) { wsStatusText('no snapshot yet'); return; }
    wsLoadPreview(state.last_snapshot);
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
    wsPreview = reply;
    wsRenderPreview(reply);
    wsStatusText('preview');
    if (onReady) onReady();
  });
}

function wsDomainRow(d) {
  const checked = d.status === 'ok' || d.status === 'size_mismatch' ? 'checked' : '';
  const note = d.status === 'size_mismatch' ? ` (${wsEsc(d.note)})` : '';
  return `<label style="display:block"><input type="checkbox" class="ws-domain" ` +
    `data-domain="${wsEsc(d.domain_id)}" ${checked}> ` +
    `${wsEsc(d.display_name)} — ${wsEsc(d.status)}${note}</label>`;
}

function wsRenderPreview(pv) {
  if (!wsEl.wsPreview) return;
  const remap = (pv.path_remap_needed || []).map((r) => `<div>⚠️ ${wsEsc(r)}</div>`);
  const rows = (pv.domains || []).map(wsDomainRow);
  wsEl.wsPreview.style.display = '';
  if (wsEl.wsRestoreActions) wsEl.wsRestoreActions.style.display = '';
  wsEl.wsPreview.innerHTML = `<b>${wsEsc(pv.name || '')}</b> · ${wsEsc(pv.created_utc || '')} · ` +
    `${wsEsc((pv.app || {}).build || '')} · ${wsEsc(pv.snapshot_kind || '')}<br>` +
    `${remap.join('')}${rows.join('')}`;
}

function wsChosenDomains() {
  return [...document.querySelectorAll('.ws-domain:checked')].map((c) => c.dataset.domain);
}

function wsSkipRow(skip) {
  const action = skip.recommended_action ? ` → ${skip.recommended_action}` : '';
  return `skipped ${skip.domain_id} [${skip.stage || 'policy'}]: ${skip.cause}${action}`;
}

function wsRestoredRows(reply) {
  const rows = [`Result: ${reply.result}`,
    `Restored: ${(reply.restored || []).join(', ') || '—'}`];
  for (const item of reply.migrated || []) rows.push(`migrated: ${item.domain_id} — ${item.note}`);
  for (const skip of reply.skipped || []) rows.push(wsSkipRow(skip));
  if (reply.backup) rows.push(`recovery backup: ${reply.backup}`);
  return rows;
}

function wsRestoreSummary(reply) {
  if (reply.ok === false && !reply.restored) {
    return { title: 'Restore failed', rows: [reply.error || 'unknown error'] };
  }
  return { title: 'Workspace restore', rows: wsRestoredRows(reply),
    openPath: reply.workspace, raw: reply };
}

function wsRestore(selected) {
  if (wsPreview) { wsRunRestore(wsPreview.root, selected); return; }
  wsStatusText('loading last snapshot…');
  _call('get_workspace_state').then((raw) => {
    const state = wsParse(raw);
    if (!state.last_snapshot) {
      // never a silent no-op: Restore All/Selected without a preview loads last
      wsStatusText('nothing to restore');
      wsRenderResult({ title: 'Nothing to restore',
        rows: ['No snapshot yet — save a workspace or Browse… to one first.'] });
      return;
    }
    wsLoadPreview(state.last_snapshot, () => wsRunRestore(state.last_snapshot, selected));
  });
}

function wsRunRestore(root, selected) {
  wsStatusText('restoring…');
  _call('restore_workspace', root, JSON.stringify({ selected })).then((raw) => {
    const reply = wsParse(raw);
    wsStatusText(reply.ok === false ? 'restore failed' : 'restored');
    wsRenderResult(wsRestoreSummary(reply));
    wsHidePreview();
    wsAfterRestore(reply);
    wsRefresh();
  });
}

// Restored values must reach the LIVE UI, not just the files (2026-09-25 bug:
// restore changed the stores but every panel kept showing pre-restore values,
// and the next Settings save clobbered the restore right back).
const WS_LIVE_PANELS = ['UrlList', 'ImageQueue', 'ProgressPanel', 'SettingsPanel'];

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
  if (window.SettingsPanel?.loadCooldownConfig) window.SettingsPanel.loadCooldownConfig();
  if (window.WatcherPanel?.loadConfig) window.WatcherPanel.loadConfig();
}

function wsRefreshLists(restored) {
  if (restored.indexOf('window_presets') >= 0 && window.WindowPresets?.refresh) {
    window.WindowPresets.refresh();
  }
  if (restored.indexOf('captcha_stats') >= 0 && window.CaptchaPanel?.refresh) {
    window.CaptchaPanel.refresh();
  }
}

function wsHidePreview() {
  wsPreview = null;
  if (wsEl.wsPreview) wsEl.wsPreview.style.display = 'none';
  if (wsEl.wsRestoreActions) wsEl.wsRestoreActions.style.display = 'none';
}

function wsWire() {
  Boot.bindOnceById('wsSaveBtn', 'click', () => wsSaveWorkspace(''), 'wsSave');
  Boot.bindOnceById('wsSaveAsBtn', 'click', () => {
    _call('browse_workspace_folder', 'save-base').then((raw) => {
      const reply = wsParse(raw);
      if (reply.ok) wsSaveWorkspace(reply.path);
    });
  }, 'wsSaveAs');
  Boot.bindOnceById('wsBrowseBtn', 'click', () => wsBrowseAndPreview('restore-source'), 'wsBrowse');
  Boot.bindOnceById('wsLoadLastBtn', 'click', wsLoadLast, 'wsLoadLast');
  Boot.bindOnceById('wsRestoreAllBtn', 'click', () => wsRestore(null), 'wsRestoreAll');
  Boot.bindOnceById('wsRestoreSelectedBtn', 'click', () => wsRestore(wsChosenDomains()), 'wsRestoreSel');
  Boot.bindOnceById('wsCancelPreviewBtn', 'click', wsHidePreview, 'wsCancel');
  Boot.bindOnceById('wsRecentList', 'click', wsOpenFromClick, 'wsRecentOpen');
  Boot.bindOnceById('wsResult', 'click', wsOpenFromClick, 'wsResultOpen');
}

function wsOpenFromClick(event) {
  const target = event.target.closest('[data-open]');
  if (!target) return;
  if (event.preventDefault) event.preventDefault();
  _call('open_workspace_path', target.dataset.open);
}

function wsInit() {
  for (const id of WS_IDS) wsEl[id] = document.getElementById(id);
  if (!wsEl.wsSaveBtn) return;   // not mounted (headless harness) — nothing to bind
  wsBridge = (typeof Boot !== 'undefined') ? Boot._bridge() : window.bridge;
  wsWire();
  wsHidePreview();
  wsRefresh();
}

const WorkspacePanel = { init: wsInit };
if (typeof window !== 'undefined') window.WorkspacePanel = WorkspacePanel;

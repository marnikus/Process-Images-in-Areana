/**
 * panels/workspace.js — the "Global Saving System" window (19th window, I-51).
 *
 * MOUNT ONLY: grab the elements, bind the buttons, publish the panel. The work
 * lives in three slices loaded before this file (audit #3 L9, RULE 18.2):
 *   workspace/bridge.js  — the one bridge transport (`_call`, `wsParse`)
 *   workspace/render.js  — every DOM write (checklist, result, recent list)
 *   workspace/flow.js    — what the buttons do + the RULE 24 live sync
 *
 * `winWorkspace` is registered in every registry (Python catalog,
 * constants.js, store.js winElIds, _PANEL_INITS) — never an L-5 orphan.
 */
'use strict';

function wsWire() {
  Boot.bindOnceById('wsSaveBtn', 'click', () => wsSaveWorkspace(''), 'wsSave');
  Boot.bindOnceById('wsSaveAsBtn', 'click', () => {
    _call('browse_workspace_folder', 'save-base').then((raw) => {
      const reply = wsParse(raw);
      if (reply.ok) wsSaveWorkspace(reply.path);
    });
  }, 'wsSaveAs');
  Boot.bindOnceById('wsBrowseBtn', 'click', () => wsBrowseAndPreview('restore-source'), 'wsBrowse');
  Boot.bindOnceById('wsLoadLastBtn', 'click', () => wsLoadLast(), 'wsLoadLast');
  Boot.bindOnceById('wsRestoreAllBtn', 'click', () => wsRestore(null), 'wsRestoreAll');
  Boot.bindOnceById('wsRestoreSelectedBtn', 'click',
    () => wsRestore(wsChosenDomains()), 'wsRestoreSel');
  Boot.bindOnceById('wsCancelPreviewBtn', 'click', wsHidePreview, 'wsCancel');
  Boot.bindOnceById('wsRecentList', 'click', wsPanelClick, 'wsRecentClick');
  Boot.bindOnceById('wsResult', 'click', wsPanelClick, 'wsResultClick');
}

function wsPanelClick(event) {
  const loadTarget = event.target.closest('[data-load]');
  if (loadTarget) {
    if (event.preventDefault) event.preventDefault();
    wsLoadPreview(loadTarget.dataset.load);   // "load" — into the preview/restore flow
    return;
  }
  const target = event.target.closest('[data-open]');
  if (!target) return;
  if (event.preventDefault) event.preventDefault();
  _call('open_workspace_path', target.dataset.open);
}

function wsInit() {
  wsElements(WS_IDS);
  if (!wsEl.wsSaveBtn) return;   // not mounted (headless harness) — nothing to bind
  wsBindBridge();
  wsWire();
  wsHidePreview();
  wsRefresh();
}

const WorkspacePanel = { init: wsInit };
if (typeof window !== 'undefined') window.WorkspacePanel = WorkspacePanel;

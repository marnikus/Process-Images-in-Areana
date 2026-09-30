/**
 * panels/workspace/bridge.js — the one way this window talks to the bridge.
 *
 * WS_IDS is the element list the mount grabs; `wsParse` decodes every reply;
 * `_call` resolves the slot through `Boot.needBridge` and always resolves
 * (never rejects), because a QWebChannel slot that answers `''` must still
 * reach the panel as a value it can refuse.
 *
 * Sliced from `panels/workspace.js` (audit #3 L9) — this file owns the
 * transport, nothing else.
 */
'use strict';

const WS_IDS = ['wsStatus', 'wsName', 'wsDescription', 'wsSaveBtn', 'wsSaveAsBtn',
  'wsBrowseBtn', 'wsLoadLastBtn', 'wsPreview', 'wsRestoreActions',
  'wsRestoreAllBtn', 'wsRestoreSelectedBtn', 'wsCancelPreviewBtn',
  'wsRecentList', 'wsResult'];

function wsParse(raw) {
  try { return JSON.parse(raw || '{}'); } catch (e) { return { ok: false, error: 'bad reply' }; }
}

function _call(name, ...args) {
  // QWebChannel slots reply through a trailing callback the caller passes —
  // without it the return value is silently dropped (the classic dead-slot
  // bug). Boot.needBridge = the slot bound to the bridge, or null + ONE
  // warning — never silent.
  const boot = (typeof Boot !== 'undefined') ? Boot : null;
  const fn = boot ? boot.needBridge(name)
    : (wsBridge && typeof wsBridge[name] === 'function' ? wsBridge[name].bind(wsBridge) : null);
  if (!fn) return Promise.resolve(null);
  return new Promise((resolve) => {
    try { fn(...args, (raw) => resolve(raw)); }
    catch (e) { console.error(`[WorkspacePanel] ${name} failed`, e); resolve(null); }
  });
}

function wsBindBridge(bridge) {
  wsBridge = bridge || (typeof Boot !== 'undefined' ? Boot._bridge() : window.bridge);
}

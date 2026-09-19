/* folder-picker.js — legacy state/restore panel for the Folder window.
   RULE18 file 150-300.

   BUG 03.4/03.5: Browse / Scan / New-Batch / Enter are owned by
   FolderBrowse (folder-picker-browse.js) — single binding, and every
   call goes through BridgeCall so a missing meta-object entry can no
   longer make a button silently dead. The old entry points below
   delegate so nothing breaks if they are still called from elsewhere. */
'use strict';

const FolderPicker = {
  init() {},

  _browse() { return window.FolderBrowse || {}; },

  restore(state) {
    if (!state) return;
    if (!state.folder) return;
    const el = document.getElementById('folderPathDisplay');
    if (el) el.textContent = state.folder.root_path || 'No folder selected';
    const inp = document.getElementById('folderPathInput');
    if (inp && state.folder.root_path) inp.value = state.folder.root_path;
    const stats = document.getElementById('folderStats');
    if (stats && state.images) this._renderStats(stats, state.images);
  },

  _renderStats(statsEl, images) {
    const total = images.length;
    const pending = images.filter(i=>i.status==='pending').length;
    statsEl.innerHTML = `<span><b>${total}</b> images</span><span><b>${pending}</b> pending</span>`;
  },

  /* --- legacy entry points (delegated, never bind buttons) --- */
  pickFolder() { this._browse().browse && this._browse().browse(); },

  setPath(p) { this._browse().applyTyped && this._browse().applyTyped(p); },

  scan() { this._browse().scan && this._browse().scan(); },

  scanNewBatch() { this._browse().scanNewBatch && this._browse().scanNewBatch(); }
};

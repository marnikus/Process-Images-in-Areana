/* folder-picker.js — RULE18 file 150-300, CC≤10 via helpers
   2026-10-02 bugfix: listeners bound once (Boot.bindOnce), a missing bridge
   slot is reported instead of silently returning, the New-Batch confirm uses
   the in-app Dialog (native confirm() is unavailable in QtWebEngine).
   ids: folderPickBtn, folderScanBtn, folderScanNewBtn, folderPathInput, folderPathDisplay. */
'use strict';

const FolderPicker = {
  init() {
    const bind = (id, ev, fn) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (window.Boot) window.Boot.bindOnce(el, ev, fn, `folder-picker:${id}`); else el.addEventListener(ev, fn);
    };
    bind('folderPickBtn', 'click', () => this.pickFolder());
    bind('folderScanBtn', 'click', () => this.scan());
    bind('folderScanNewBtn', 'click', () => this.scanNewBatch());
    bind('folderPathInput', 'keydown', (e) => { if (e.key==='Enter') this.setPath(e.target.value); });
  },

  _slot(name) {
    if (window.Boot) return window.Boot.needBridge(name);
    const b = window.App && window.App.bridge;
    return b && b[name] ? b[name].bind(b) : null;
  },

  _setDisplay(path) {
    const el = document.getElementById('folderPathDisplay');
    if (el) el.textContent = path || 'No folder selected';
    const inp = document.getElementById('folderPathInput');
    if (inp && path) inp.value = path;
  },

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

  _onPickFolder(res) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        this._setDisplay(r.path);
        LogConsole.log('Folder selected: ' + r.path, 'success');
      } else if (r.cancelled) {
        LogConsole.log('Folder pick cancelled', 'info');
      } else {
        LogConsole.log('Folder pick failed: ' + r.error, 'error');
      }
    } catch (e) { LogConsole.log('Folder pick: bad reply', 'error'); }
  },

  pickFolder() {
    const pick = this._slot('pick_folder');
    if (!pick) return;
    const inp = document.getElementById('folderPathInput');
    const startDir = inp ? inp.value.trim() : '';
    pick(startDir, (res) => this._onPickFolder(res));
  },

  _onSetPath(res) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        this._setDisplay(r.path);
        LogConsole.log('Folder path set: ' + r.path, 'success');
      } else LogConsole.log('Set path failed: ' + r.error, 'error');
    } catch (e) { LogConsole.log('Set path: bad reply', 'error'); }
  },

  setPath(p) {
    const set = this._slot('set_folder_path');
    if (!set) return;
    const path = (p || '').trim();
    if (!path) { LogConsole.log('⚠ Type a folder path first', 'warn'); return; }
    set(path, (res) => this._onSetPath(res));
  },

  _onScan(res) {
    try {
      const r = JSON.parse(res);
      if (r.ok && r.pending) LogConsole.log('🔍 Scan started in background — UI stays responsive', 'info');
      else if (r.ok) LogConsole.log(`Scan complete: ${r.count} images found`, 'success');
      else if (r.pending) LogConsole.log('Scan already in progress, please wait', 'warn');
      else LogConsole.log('Scan failed: ' + r.error, 'error');
    } catch (e) {}
  },

  scan() {
    const scan = this._slot('scan_folder');
    if (!scan) return;
    LogConsole.log('Scanning folder... (non-blocking)', 'info');
    scan((res) => this._onScan(res));
  },

  _onScanNewBatch(res) {
    try {
      const r = JSON.parse(res);
      if (r.ok && r.pending) LogConsole.log(`✅ New batch: cleared ${r.cleared||0} old — scanning in background`, 'success');
      else if (r.ok) LogConsole.log(`✅ New batch: cleared ${r.cleared||0} old, ${r.count} new images found`, 'success');
      else LogConsole.log('New batch scan failed: ' + (r.error||res), 'error');
    } catch (e) { LogConsole.log('New batch scan done','info'); }
  },

  _doScan() {
    if (!App.bridge?.scan_folder) return;
    LogConsole.log('Scanning folder as new batch...', 'info');
    App.bridge.scan_folder((res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log(`Scan complete: ${r.count} images found`, 'success');
        else LogConsole.log('Scan failed: ' + r.error, 'error');
      } catch (e) {}
    });
  },

  _clearThenScan() {
    const doScan = () => this._doScan();
    if (App.bridge?.clear_queue) {
      App.bridge.clear_queue((res) => {
        try {
          const r = JSON.parse(res);
          LogConsole.log(`🗑 Cleared ${r.count} images — starting new batch scan`, 'warn');
        } catch(e){}
        setTimeout(doScan, 200);
      });
    } else {
      doScan();
    }
  },

  _startNewBatch() {
    const slot = this._slot('scan_folder_new_batch');
    if (slot) {
      LogConsole.log('🗑 Clearing old list + scanning new batch... (non-blocking)', 'warn');
      slot((res) => this._onScanNewBatch(res));
      return;
    }
    this._clearThenScan();
  },

  scanNewBatch() {
    const text = 'Start NEW batch? This will clear the current list and scan the folder anew.';
    if (window.Dialog?.confirm) { window.Dialog.confirm('New batch scan', text, 'Clear & scan', () => this._startNewBatch()); return; }
    if (typeof confirm !== 'function' || confirm(text)) this._startNewBatch();
  }
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.FolderPicker = FolderPicker;

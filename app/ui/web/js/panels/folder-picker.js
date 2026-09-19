/* folder-picker.js — RULE18 file 150-300, CC≤10 via helpers */
'use strict';

const FolderPicker = {
  init() {
    const btn = document.getElementById('folderPickBtn');
    const scanBtn = document.getElementById('folderScanBtn');
    const scanNewBtn = document.getElementById('folderScanNewBtn');
    const pathInput = document.getElementById('folderPathInput');
    if (btn) btn.addEventListener('click', () => this.pickFolder());
    if (scanBtn) scanBtn.addEventListener('click', () => this.scan());
    if (scanNewBtn) scanNewBtn.addEventListener('click', () => this.scanNewBatch());
    if (pathInput) pathInput.addEventListener('keydown', (e) => { if (e.key==='Enter') this.setPath(pathInput.value); });
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
        document.getElementById('folderPathDisplay').textContent = r.path;
        document.getElementById('folderPathInput').value = r.path;
        LogConsole.log('Folder selected: ' + r.path, 'success');
      } else if (r.cancelled) {
        LogConsole.log('Folder pick cancelled', 'info');
      } else {
        LogConsole.log('Folder pick failed: ' + r.error, 'error');
      }
    } catch (e) {}
  },

  pickFolder() {
    if (!App.bridge?.pick_folder) return;
    const inp = document.getElementById('folderPathInput');
    const startDir = inp ? inp.value.trim() : '';
    App.bridge.pick_folder(startDir, (res) => this._onPickFolder(res));
  },

  _onSetPath(res) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        document.getElementById('folderPathDisplay').textContent = r.path;
        LogConsole.log('Folder path set: ' + r.path, 'success');
      } else LogConsole.log('Set path failed: ' + r.error, 'error');
    } catch (e) {}
  },

  setPath(p) {
    if (!App.bridge?.set_folder_path) return;
    App.bridge.set_folder_path(p, (res) => this._onSetPath(res));
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
    if (!App.bridge?.scan_folder) return;
    LogConsole.log('Scanning folder... (non-blocking)', 'info');
    App.bridge.scan_folder((res) => this._onScan(res));
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

  scanNewBatch() {
    if (!confirm('Start NEW batch? This will clear current list and scan folder anew.')) return;
    if (App.bridge?.scan_folder_new_batch) {
      LogConsole.log('🗑 Clearing old list + scanning new batch... (non-blocking)', 'warn');
      App.bridge.scan_folder_new_batch((res) => this._onScanNewBatch(res));
      return;
    }
    this._clearThenScan();
  }
};

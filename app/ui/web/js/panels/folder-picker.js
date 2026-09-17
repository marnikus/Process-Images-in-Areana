/* folder-picker.js */
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
    if (!state || !state.folder) return;
    const el = document.getElementById('folderPathDisplay');
    if (el) el.textContent = state.folder.root_path || 'No folder selected';
    const inp = document.getElementById('folderPathInput');
    if (inp && state.folder.root_path) inp.value = state.folder.root_path;
    const stats = document.getElementById('folderStats');
    if (stats && state.images) {
      const total = state.images.length;
      const pending = state.images.filter(i=>i.status==='pending').length;
      stats.innerHTML = `<span><b>${total}</b> images</span><span><b>${pending}</b> pending</span>`;
    }
  },

  pickFolder() {
    if (App.bridge && App.bridge.pick_folder) {
      const inp = document.getElementById('folderPathInput');
      const startDir = inp ? inp.value.trim() : '';
      App.bridge.pick_folder(startDir, (res) => {
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
      });
    }
  },

  setPath(p) {
    if (App.bridge && App.bridge.set_folder_path) {
      App.bridge.set_folder_path(p, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            document.getElementById('folderPathDisplay').textContent = r.path;
            LogConsole.log('Folder path set: ' + r.path, 'success');
          } else LogConsole.log('Set path failed: ' + r.error, 'error');
        } catch (e) {}
      });
    }
  },

  scan() {
    if (App.bridge && App.bridge.scan_folder) {
      LogConsole.log('Scanning folder... (non-blocking)', 'info');
      App.bridge.scan_folder((res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok && r.pending) LogConsole.log('🔍 Scan started in background — UI stays responsive', 'info');
          else if (r.ok) LogConsole.log(`Scan complete: ${r.count} images found`, 'success');
          else if (r.pending) LogConsole.log('Scan already in progress, please wait', 'warn');
          else LogConsole.log('Scan failed: ' + r.error, 'error');
        } catch (e) {}
      });
    }
  },

  scanNewBatch() {
    if (!confirm('Start NEW batch? This will clear current list and scan folder anew.')) return;
    if (App.bridge && App.bridge.scan_folder_new_batch) {
      LogConsole.log('🗑 Clearing old list + scanning new batch... (non-blocking)', 'warn');
      App.bridge.scan_folder_new_batch((res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok && r.pending) LogConsole.log(`✅ New batch: cleared ${r.cleared||0} old — scanning in background, UI stays responsive`, 'success');
          else if (r.ok) LogConsole.log(`✅ New batch: cleared ${r.cleared||0} old, ${r.count} new images found`, 'success');
          else LogConsole.log('New batch scan failed: ' + (r.error||res), 'error');
        } catch (e) { LogConsole.log('New batch scan done','info'); }
      });
      return;
    }
    const doScan = () => {
      if (App.bridge && App.bridge.scan_folder) {
        LogConsole.log('Scanning folder as new batch...', 'info');
        App.bridge.scan_folder((res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok) LogConsole.log(`Scan complete: ${r.count} images found`, 'success');
            else LogConsole.log('Scan failed: ' + r.error, 'error');
          } catch (e) {}
        });
      }
    };
    if (App.bridge && App.bridge.clear_queue) {
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
  }
};

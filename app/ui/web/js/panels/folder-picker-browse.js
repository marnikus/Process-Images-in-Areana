/* folder-picker-browse.js — restores the Browse folder dialog (BUG 03.4)
   RULE18: file 150-300, func <= 30, CC <= 10

   Root causes in folder-picker.js:
   1. `if (!App.bridge?.pick_folder) return;` — when the slot was not exposed
      the Browse click returned immediately: no dialog, no error, no log.
   2. Failures only reached LogConsole. If the Log window was closed the user
      saw nothing at all and concluded "the button is dead".
   3. No busy state: a second click while the modal was open queued another
      dialog behind the first.

   Pairs with app/ui/panels/folder_browse.py (real parent window + native ->
   Qt fallback chain).
*/
'use strict';

window.FolderBrowse = {
  requires: ['folderPickBtn'],
  _busy: false,
  _scanning: false,

  /* Sole owner of Browse / Scan / New-Batch / Enter — the legacy
     folder-picker.js no longer binds these (single binding, and every
     call goes through BridgeCall so a missing meta-object entry can
     never make a button silently dead, BUG 03.5). */
  init() {
    const btn = document.getElementById('folderPickBtn');
    if (btn) btn.addEventListener('click', () => this.browse());
    const scanBtn = document.getElementById('folderScanBtn');
    if (scanBtn) scanBtn.addEventListener('click', () => this.scan());
    const scanNewBtn = document.getElementById('folderScanNewBtn');
    if (scanNewBtn) scanNewBtn.addEventListener('click', () => this.scanNewBatch());
    const input = document.getElementById('folderPathInput');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); this.applyTyped(input.value); }
      });
    }
  },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
  },

  /* Errors must be visible even with the Log window closed. */
  status(msg, level) {
    let el = document.getElementById('folderPickStatus');
    const anchor = document.getElementById('folderPathDisplay')
      || document.getElementById('folderPickBtn');
    if (!el && anchor) {
      el = document.createElement('div');
      el.id = 'folderPickStatus';
      el.style.cssText = 'font-size:11px; margin-top:4px;';
      anchor.parentNode.appendChild(el);
    }
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = level === 'error' ? 'var(--error, #bf616a)'
      : level === 'warn' ? 'var(--warn, #d08770)' : 'var(--text-muted)';
  },

  _setBusy(state) {
    this._busy = state;
    const btn = document.getElementById('folderPickBtn');
    if (!btn) return;
    btn.disabled = state;
    btn.textContent = state ? 'Opening…' : 'Browse';
  },

  browse() {
    if (this._busy) { this._log('Folder dialog already open', 'warn'); return; }
    const input = document.getElementById('folderPathInput');
    const start = input ? input.value.trim() : '';
    this._setBusy(true);
    this.status('Opening folder dialog…');
    BridgeCall.invoke('pick_folder', [start], (r) => this._onPicked(r));
  },

  _onPicked(r) {
    this._setBusy(false);
    if (r.queued) { this.status('Bridge not ready — try again', 'warn'); return; }
    if (r.cancelled) { this.status('Cancelled'); this._log('Folder pick cancelled', 'info'); return; }
    if (r.ok === false) {
      const msg = r.error || 'Folder dialog failed';
      this.status(msg, 'error');
      this._log(`❌ Browse: ${msg}`, 'error');
      return;
    }
    this.applyPath(r.path, r.via);
  },

  applyPath(path, via) {
    const display = document.getElementById('folderPathDisplay');
    if (display) display.textContent = path;
    const input = document.getElementById('folderPathInput');
    if (input) input.value = path;
    this.status(`Selected${via ? ` (${via} dialog)` : ''}`);
    this._log(`📁 Folder selected: ${path}`, 'success');
    this.scan();  // auto-scan the freshly selected folder
  },

  /* Scan runs in a background worker; the queue re-renders itself when
     the arena-state signal lands (listeners._handleArenaState). */
  scan() {
    if (this._scanning) { this.status('Scan already running — queue updates when it finishes', 'warn'); return; }
    this._scanning = true;
    this.status('🔍 Scanning folder… (non-blocking)');
    this._log('Scanning folder… (non-blocking)', 'info');
    BridgeCall.invoke('scan_folder', [], (r) => {
      this._scanning = false;
      if (r.queued) { this.status('Bridge not ready — try again', 'warn'); return; }
      if (r.pending) { this.status('Scanning in background — the queue fills in automatically'); return; }
      if (r.ok) { this.status(`Scan complete: ${r.count || 0} images found`, r.count ? '' : 'warn'); return; }
      this.status(`Scan failed: ${r.error || 'unknown error'}`, 'error');
      this._log(`❌ Scan failed: ${r.error || 'unknown error'}`, 'error');
    });
  },

  scanNewBatch() {
    const proceed = () => this._scanNewBatch();
    if (window.Dialog && Dialog.confirm) {
      Dialog.confirm('New batch',
        'Start NEW batch? This clears the current list and scans the folder anew.', 'Start', proceed);
      return;
    }
    if (!confirm('Start NEW batch? This will clear current list and scan folder anew.')) return;
    proceed();
  },

  _scanNewBatch() {
    this._scanning = true;
    this.status('🗑 Clearing list + scanning new batch… (non-blocking)');
    this._log('🗑 Clearing old list + scanning new batch… (non-blocking)', 'warn');
    BridgeCall.invoke('scan_folder_new_batch', [], (r) => {
      this._scanning = false;
      if (r.queued) { this.status('Bridge not ready — try again', 'warn'); return; }
      if (r.pending) { this.status(`New batch: cleared ${r.cleared || 0} old — scanning in background`, 'warn'); return; }
      if (r.ok) { this.status(`New batch: cleared ${r.cleared || 0} old, ${r.count || 0} new images`); return; }
      this.status(`New batch scan failed: ${r.error || 'unknown error'}`, 'error');
      this._log(`❌ New batch scan failed: ${r.error || 'unknown error'}`, 'error');
    });
  },

  /* Typing a path must work even when no dialog is available at all. */
  applyTyped(value) {
    const path = (value || '').trim();
    if (!path) { this.status('Type a folder path', 'warn'); return; }
    BridgeCall.invoke('set_folder_path', [path], (r) => {
      if (r.ok === false) {
        this.status(r.error || 'Path rejected', 'error');
        this._log(`❌ ${r.error || 'Path rejected'}`, 'error');
        return;
      }
      this.applyPath(r.path, 'typed');
    });
  },
};

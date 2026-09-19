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

  init() {
    const btn = document.getElementById('folderPickBtn');
    btn.addEventListener('click', () => this.browse());
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
    if (window.FolderPicker && FolderPicker.scan) FolderPicker.scan();
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

/* ═══════════════════════════════════════════════════════════════
   log-console.js — Log console display with auto-scroll
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const LogConsole = {
  _el: null,
  _maxEntries: 500,
  _lastMsg: '',
  _lastTime: 0,
  _lastCount: 0,

  init() {
    this._el = document.getElementById('logConsole');
  },

  log(message, level = 'info') {
    if (!this._el) this._el = document.getElementById('logConsole');
    if (!this._el) return;
    const nowMs = Date.now();
    // Dedup identical messages within 600ms (prevents double logs from old bridge emitting both signals)
    if (message === this._lastMsg && (nowMs - this._lastTime) < 600) {
      this._lastCount++;
      // Update last entry to show count if repeated
      const lastEl = this._el.lastChild;
      if (lastEl && this._lastCount <= 3) {
        lastEl.textContent = lastEl.textContent.replace(/ \(x\d+\)$/, '') + ` (x${this._lastCount+1})`;
      }
      return;
    }
    this._lastMsg = message;
    this._lastTime = nowMs;
    this._lastCount = 0;
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + (level || '');
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    entry.textContent = `[${ts}] ${message}`;
    this._el.appendChild(entry);
    // auto-scroll
    this._el.scrollTop = this._el.scrollHeight;
    // trim old entries
    while (this._el.children.length > this._maxEntries) {
      this._el.removeChild(this._el.firstChild);
    }
  },

  clear() {
    if (this._el) this._el.innerHTML = '';
  },
};

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => LogConsole.init());

/* ═══════════════════════════════════════════════════════════════
   log-console.js — Log console display with auto-scroll
   RULE18: CC≤10 via helpers
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

  _ensureEl() {
    if (!this._el) this._el = document.getElementById('logConsole');
    return !!this._el;
  },

  _isDup(message) {
    const nowMs = Date.now();
    return message === this._lastMsg && (nowMs - this._lastTime) < 600;
  },

  _handleDup() {
    this._lastCount++;
    const lastEl = this._el.lastChild;
    if (!lastEl) return true;
    if (this._lastCount > 3) return true;
    lastEl.textContent = lastEl.textContent.replace(/ \(x\d+\)$/, '') + ` (x${this._lastCount+1})`;
    return true;
  },

  _createEntry(message, level) {
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + (level || '');
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    entry.textContent = `[${ts}] ${message}`;
    this._el.appendChild(entry);
  },

  _scheduleScroll() {
    if (this._scrollTimer) return;
    this._scrollTimer = setTimeout(() => {
      this._scrollTimer = null;
      try {
        if (this._el) this._el.scrollTop = this._el.scrollHeight;
      } catch (e) {}
    }, 100);
  },

  _trim() {
    while (this._el.children.length > this._maxEntries) {
      this._el.removeChild(this._el.firstChild);
    }
  },

  log(message, level = 'info') {
    if (!this._ensureEl()) return;
    if (this._isDup(message)) {
      this._handleDup();
      return;
    }
    this._lastMsg = message;
    this._lastTime = Date.now();
    this._lastCount = 0;
    this._createEntry(message, level);
    this._scheduleScroll();
    this._trim();
  },

  clear() {
    if (this._el) this._el.innerHTML = '';
  },
};

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => LogConsole.init());

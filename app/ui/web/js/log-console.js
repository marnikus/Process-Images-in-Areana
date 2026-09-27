/* ═══════════════════════════════════════════════════════════════
   log-console.js — Log console display; follows the bottom only while the
   user is there, every line kept for "Copy all" (log-tools.js, I-69)
   RULE18: CC≤10 via helpers
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const LogConsole = {
  _el: null,
  _maxEntries: 500,
  _lastMsg: '',
  _lastTime: 0,
  _lastCount: 0,

  init() { this._ensureEl(); },

  _ensureEl() {
    if (!this._el) this._el = document.getElementById('logConsole');
    return !!this._el;
  },

  _isDup(message) {
    return message === this._lastMsg && (Date.now() - this._lastTime) < 600;
  },

  _handleDup() {
    this._lastCount++;
    const lastEl = this._el.lastChild;
    if (!lastEl || this._lastCount > 3) return true;
    lastEl.textContent = lastEl.textContent.replace(/ \(x\d+\)$/, '') + ` (x${this._lastCount+1})`;
    window.LogTools?.replaceLast(lastEl.textContent);
    return true;
  },

  _createEntry(message, level) {
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + (level || '');
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    entry.textContent = `[${ts}] ${message}`;
    const follow = window.LogTools?.atBottom(this._el) ?? true;  // asked BEFORE the append
    this._el.appendChild(entry);
    window.LogTools?.record(entry.textContent);
    if (follow) this._scheduleScroll();  // scrolled up = the view stays put
  },

  _scheduleScroll() {
    if (this._scrollTimer) return;
    this._scrollTimer = setTimeout(() => {
      this._scrollTimer = null;
      try { if (this._el) this._el.scrollTop = this._el.scrollHeight; } catch (e) {}
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
    this._trim();
  },

  clear() {
    if (this._el) this._el.innerHTML = '';
    window.LogTools?.clear();
  },
};

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => LogConsole.init());

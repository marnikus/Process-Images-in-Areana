/* ═══════════════════════════════════════════════════════════════
   log-console.js — Log console: follow-the-end scrolling + Copy all
   RULE18: CC≤10 via helpers

   2026-09-27 (design D-5):
   * Follow mode: a new line scrolls to the end only while the view IS at
     the end. Scrolling up pauses following and shows the "⬇ N new" chip;
     scrolling back down (or the chip) resumes. While paused the screen
     keeps up to _maxHistory lines (the ones being read are not trimmed
     away) and returns to _maxEntries once following resumes. CSS `overflow-anchor: none` keeps
     Chromium's scroll anchoring from moving the view behind our back.
   * Copy all: the whole session history (up to _maxHistory lines, more
     than the _maxEntries kept on screen) to the clipboard.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const LogConsole = {
  _el: null,
  _maxEntries: 500,
  _maxHistory: 5000,
  _history: [],
  _follow: true,
  _unseen: 0,
  _slackPx: 8,
  _lastMsg: '',
  _lastTime: 0,
  _lastCount: 0,

  init() {
    this._el = document.getElementById('logConsole');
    this._bind('copyLogBtn', () => this.copyAll());
    this._bind('logFollowBtn', () => this.jumpToEnd());
    if (this._el) this._el.addEventListener('scroll', () => this._onScroll());
    this._renderFollow();
  },

  _bind(id, fn) {
    const btn = document.getElementById(id);
    if (btn) btn.addEventListener('click', fn);
  },

  _ensureEl() {
    if (!this._el) this._el = document.getElementById('logConsole');
    return !!this._el;
  },

  _atEnd() {
    const el = this._el;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= this._slackPx;
  },

  _onScroll() {
    if (!this._el) return;
    this._follow = this._atEnd();
    if (this._follow) this._unseen = 0;
    this._renderFollow();
  },

  _renderFollow() {
    const chip = document.getElementById('logFollowBtn');
    if (!chip) return;
    chip.hidden = this._follow;
    chip.textContent = this._unseen ? `⬇ ${this._unseen} new` : '⬇ Follow';
  },

  jumpToEnd() {
    this._follow = true;
    this._unseen = 0;
    if (this._el) this._el.scrollTop = this._el.scrollHeight;
    this._renderFollow();
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
    this._history[this._history.length - 1] = lastEl.textContent;
    return true;
  },

  _createEntry(message, level) {
    const entry = document.createElement('div');
    entry.className = 'log-entry ' + (level || '');
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    entry.textContent = `[${ts}] ${message}`;
    this._el.appendChild(entry);
    return entry.textContent;
  },

  _remember(line) {
    this._history.push(line);
    const extra = this._history.length - this._maxHistory;
    if (extra > 0) this._history.splice(0, extra);
  },

  _scheduleScroll() {
    if (!this._follow) {
      this._unseen++;
      this._renderFollow();
      return;
    }
    if (this._scrollTimer) return;
    this._scrollTimer = setTimeout(() => this._scrollToEnd(), 100);
  },

  _scrollToEnd() {
    this._scrollTimer = null;
    try {
      if (this._el && this._follow) this._el.scrollTop = this._el.scrollHeight;
    } catch (e) {}
  },

  _trim() {
    const keep = this._follow ? this._maxEntries : this._maxHistory;  // paused: the lines being read stay
    let removed = 0;
    while (this._el.children.length > keep) {
      removed += this._el.firstChild.offsetHeight || 0;
      this._el.removeChild(this._el.firstChild);
    }
    if (removed && !this._follow) this._el.scrollTop = Math.max(0, this._el.scrollTop - removed);
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
    this._remember(this._createEntry(message, level));
    this._trim();
    this._scheduleScroll();
  },

  allText() {
    return this._history.join('\n');
  },

  copyAll() {
    const text = this.allText();
    const clip = (typeof navigator !== 'undefined') ? navigator.clipboard : null;
    if (!clip || !clip.writeText) return this._copied(this._copyFallback(text));
    return clip.writeText(text).then(() => this._copied(true), () => this._copied(this._copyFallback(text)));
  },

  _copyFallback(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = !!document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  },

  _copied(ok) {
    const btn = document.getElementById('copyLogBtn');
    if (btn) btn.textContent = ok ? 'Copied ✓' : 'Copy failed';
    if (btn) setTimeout(() => { btn.textContent = 'Copy all'; }, 1500);
    const lines = this._history.length;
    this.log(ok ? `📋 Copied ${lines} log line(s) to the clipboard` : '⚠ Could not copy the log to the clipboard', ok ? 'success' : 'warn');
    return ok;
  },

  clear() {
    if (this._el) this._el.innerHTML = '';
    this._history = [];
    this._unseen = 0;
    this._follow = true;
    this._renderFollow();
  },
};

(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => LogConsole.init());

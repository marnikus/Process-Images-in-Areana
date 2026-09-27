/* ═══════════════════════════════════════════════════════════════
   log-tools.js — Activity Log: full history, "Copy all", follow-the-bottom
   (owner request 2026-09-27, I-69).

   • History: every line the console shows, kept past the console's 500-entry
     DOM trim (bounded at MAX_LINES), so "Copy all" copies the whole run.
   • Copy all: the clipboard write runs INSIDE the click (execCommand('copy')
     on a hidden textarea — allowed on the file:// page in QtWebEngine because
     the user asked for it); navigator.clipboard is the fallback. The result is
     logged honestly — never a silent success.
   • Follow: new lines keep the view at the bottom only while the user is
     already there. Scrolled up = the view stays put; back at the bottom =
     following again. LogConsole asks `atBottom(el)` BEFORE it appends.
   log-console.js stays at its ratcheted size: it only calls in here.
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const LogTools = {
  MAX_LINES: 50000,
  BOTTOM_SLACK_PX: 24,
  _lines: [],

  record(line) {
    this._lines.push(String(line));
    if (this._lines.length > this.MAX_LINES) this._lines.splice(0, this._lines.length - this.MAX_LINES);
  },

  // The console folds a repeated message into its last row ("… (x3)").
  replaceLast(line) {
    if (this._lines.length) this._lines[this._lines.length - 1] = String(line);
  },

  clear() { this._lines = []; },

  text() { return this._lines.join('\n'); },

  count() { return this._lines.length; },

  atBottom(el) {
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= this.BOTTOM_SLACK_PX;
  },

  _copyInGesture(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:-1000px;left:-1000px;opacity:0;';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = !!document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  },

  async _copyAsync(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      return false;
    }
  },

  async copyAll() {
    const n = this.count();
    if (!n) return this._say('📋 Log is empty — nothing to copy', 'warn');
    const text = this.text();
    const ok = this._copyInGesture(text) || await this._copyAsync(text);
    return ok ? this._say(`📋 Copied ${n} log line(s) to the clipboard`, 'success')
      : this._say('⚠ Copy failed — select the log text and press Ctrl+C', 'error');
  },

  _say(message, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(message, level);  // top-level const, not a window prop
    return level !== 'error' && level !== 'warn';
  },

  init() {
    document.getElementById('copyLogBtn')?.addEventListener('click', () => this.copyAll());
  },
};

window.LogTools = LogTools;
(window.BridgeReady || { ready: (fn) => document.addEventListener('DOMContentLoaded', () => fn(null)) })
  .ready(() => LogTools.init());

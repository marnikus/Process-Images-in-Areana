/* captcha.js — standalone Captcha window: Captcha Watcher (SDK solver) control.
   Isolation contract (2026-10-02): jobs never solve; the Watcher is the only
   solver. This panel owns: key save (masked reply, RULE 20), Watcher ON/OFF
   (same switch as the Watcher window), live solver counters, balance, and
   the pipeline's detected/cleared counters. The raw key is cleared from the
   field after a successful save and never kept in a page preset. */
'use strict';

const CaptchaPanel = {
  _status: null,

  init() {
    const on = (id, fn) => document.getElementById(id)?.addEventListener('click', fn);
    on('captchaSaveBtn', () => this.saveKey());
    on('captchaBalanceBtn', () => this.balance());
    on('captchaWatcherStartBtn', () => this.watcherOn());
    on('captchaWatcherStopBtn', () => this.watcherOff());
    on('captchaStatsBtn', () => this.refresh());
    document.getElementById('captchaKeyShow')?.addEventListener('change', (e) => {
      const k = document.getElementById('captchaApiKey');
      if (k) k.type = e.target.checked ? 'text' : 'password';
    });
    setTimeout(() => this.refresh(), 1200);
  },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
  },

  _call(name, args, cb) {
    const fn = App.bridge?.[name];
    if (!fn) return false;
    const onRes = (res) => { try { cb(JSON.parse(res)); } catch (e) { /* malformed reply */ } };
    if (args.length) fn(...args, onRes); else fn(onRes);
    return true;
  },

  refresh() {
    this.loadStatus();
    this.loadStats();
  },

  loadStatus() {
    this._call('watcher_status', [], (r) => { if (r.ok) this.renderStatus(r); });
  },

  loadStats() {
    this._call('get_captcha_stats', [], (r) => { if (r.ok) this.renderStats(r); });
  },

  saveKey() {
    const key = (document.getElementById('captchaApiKey')?.value || '').trim();
    this._call('set_captcha_api_key', [key], (r) => {
      if (!r.ok) { this._log('2Captcha key save failed: ' + (r.error || '?'), 'error'); return; }
      this._log(`2Captcha key ${r.has_key ? 'saved: ' + r.masked_key : 'cleared'}`, 'success');
      const k = document.getElementById('captchaApiKey');
      if (k) k.value = '';
      this.refresh();
    });
  },

  balance() {
    this._call('captcha_balance', [], (r) => {
      if (!r.ok) { this._log('Balance check failed: ' + (r.error || '?'), 'warn'); return; }
      setTimeout(() => this.loadStatus(), 2500);
    });
  },

  watcherOn() {
    this._call('start_watcher', [], (r) => {
      if (!r.ok) { this._log('Watcher start failed: ' + (r.error || '?'), 'error'); return; }
      const s = r.solver || {};
      if (s.ok === false) this._log('Watcher ON, but solving is disabled: ' + (s.error || '?'), 'warn');
      if (typeof WatcherPanel !== 'undefined') WatcherPanel.loadConfig();
      setTimeout(() => this.loadStatus(), 600);
    });
  },

  watcherOff() {
    this._call('stop_watcher', [], (r) => {
      if (!r.ok) { this._log('Watcher stop failed: ' + (r.error || '?'), 'error'); return; }
      if (typeof WatcherPanel !== 'undefined') WatcherPanel.loadConfig();
      setTimeout(() => this.loadStatus(), 600);
    });
  },

  onStatusUpdate(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      if (data) this.renderStatus(data);
    } catch (e) { /* ignore malformed pushes */ }
  },

  _balanceText(r) {
    if (r.balance === null || r.balance === undefined) return 'balance: —';
    return `balance: $${Number(r.balance).toFixed(2)}`;
  },

  _solverText(r) {
    if (r.running) return r.solving_tab ? `solver: ON (solving ${r.solving_tab.slice(0, 8)}…)` : 'solver: ON';
    if (!r.sdk_available) return 'solver: off (SDK missing — pip install 2captcha-python)';
    return r.has_key ? 'solver: off (turn the Watcher ON)' : 'solver: off (no key)';
  },

  _renderBadge(r) {
    const badge = document.getElementById('captchaWatcherBadge');
    if (!badge) return;
    badge.textContent = r.running ? 'solver: on' : 'solver: off';
    badge.style.background = r.running ? 'var(--bg-success, #1a3a1a)' : 'var(--bg-input)';
    badge.style.color = r.running ? '#4ade80' : 'var(--text-muted)';
  },

  renderStatus(r) {
    this._status = r;
    this._renderBadge(r);
    const line = document.getElementById('captchaStatusLine');
    if (line) {
      const key = r.has_key ? 'key: set' : 'key: (not set)';
      const err = r.last_error ? ` · last error: ${r.last_error}` : '';
      line.textContent = `${this._solverText(r)} · ${key} · ${this._balanceText(r)}${err}`;
    }
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('capStatAuto', r.solved_total ?? 0);
    set('capStatFailed', r.failed_total ?? 0);
    set('capStatTabs', r.tabs_seen ?? 0);
    if (r.balance !== null && r.balance !== undefined) set('capStatBalance', `$${Number(r.balance).toFixed(2)}`);
  },

  renderStats(r) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('capStatDetected', r.detected_total ?? 0);
    set('capStatManual', r.manual_solved ?? 0);
  },
};

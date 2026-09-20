/* captcha.js — standalone Captcha window: Captcha Watcher (SDK solver) control.
   Isolation contract (2026-10-02): jobs never solve; the Watcher is the only
   solver. This panel owns: provider dropdown (B10: 2Captcha | CapMonster
   Cloud, one key per provider), key save (masked reply, RULE 20), Watcher
   ON/OFF (same switch as the Watcher window), live solver counters, balance,
   and the pipeline's detected/cleared counters. The raw key is cleared from
   the field after a successful save and never kept in a page preset. */
'use strict';

const CaptchaPanel = {
  _status: null,
  _providers: null,   // last get_captcha_api_key reply: {provider, provider_label, providers:[…]}

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
    document.getElementById('captchaProvider')?.addEventListener('change', (e) => this.setProvider(e.target.value));
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
    this.loadProviders();
    this.loadStatus();
    this.loadStats();
  },

  loadStatus() {
    this._call('watcher_status', [], (r) => { if (r.ok) this.renderStatus(r); });
  },

  loadProviders() {
    this._call('get_captcha_api_key', [], (r) => { if (r.ok) this.renderProviders(r); });
  },

  /* Provider dropdown: value = active provider, option labels show which
     providers already have a key; hint + key label follow the selection. */
  _optionLabel(p) {
    return `${p.label}${p.has_key ? ' ✓ key set' : ' — no key'}`;
  },

  renderProviders(r) {
    if (!r || !Array.isArray(r.providers)) return;
    this._providers = r;
    const sel = document.getElementById('captchaProvider');
    if (sel) {
      const opts = Array.from(sel.options || []);
      r.providers.forEach((p) => {
        const opt = opts.find((o) => o.value === p.id);
        if (opt) opt.textContent = this._optionLabel(p);
      });
      sel.value = r.provider;
    }
    const active = r.providers.find((p) => p.id === r.provider) || {};
    const hint = document.getElementById('captchaProviderHint');
    if (hint) hint.textContent = active.has_key ? `key: ${active.masked_key || 'set'}` : 'key: (not set)';
    const label = document.getElementById('captchaKeyLabel');
    if (label) label.textContent = `${r.provider_label} API key — stored locally (config/captcha_solvers.json, 0600), masked, never in logs/presets`;
    const input = document.getElementById('captchaApiKey');
    if (input) input.placeholder = `paste ${r.provider_label} API key`;
  },

  setProvider(provider) {
    this._call('set_captcha_provider', [provider], (r) => {
      if (!r.ok) {
        this._log('Captcha provider switch failed: ' + (r.error || '?'), 'error');
        if (this._providers) this.renderProviders(this._providers);   // snap the dropdown back
        return;
      }
      this.renderProviders(r);
      this._log(`Captcha provider: ${r.provider_label}${r.has_key ? '' : ' — paste its API key and Save'}`, r.has_key ? 'info' : 'warn');
      setTimeout(() => this.loadStatus(), 300);
    });
  },

  loadStats() {
    this._call('get_captcha_stats', [], (r) => { if (r.ok) this.renderStats(r); });
  },

  _providerLabel() {
    return (this._providers && this._providers.provider_label) || '2Captcha';
  },

  saveKey() {
    const key = (document.getElementById('captchaApiKey')?.value || '').trim();
    this._call('set_captcha_api_key', [key], (r) => {
      const label = r.provider_label || this._providerLabel();
      if (!r.ok) { this._log(`${label} key save failed: ` + (r.error || '?'), 'error'); return; }
      this._log(`${label} key ${r.has_key ? 'saved: ' + r.masked_key : 'cleared'}`, 'success');
      const k = document.getElementById('captchaApiKey');
      if (k) k.value = '';
      if (Array.isArray(r.providers)) this.renderProviders(r);
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
    const via = r.provider_label ? ` via ${r.provider_label}` : '';
    if (r.running) return r.solving_tab ? `solver: ON${via} (solving ${r.solving_tab.slice(0, 8)}…)` : `solver: ON${via}`;
    if (!r.sdk_available) return 'solver: off (SDK missing — pip install 2captcha-python)';
    return r.has_key ? `solver: off${via} (turn the Watcher ON)` : `solver: off (no ${r.provider_label || 'provider'} key)`;
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
      const key = r.has_key ? `${r.provider_label || '2Captcha'} key: set` : `${r.provider_label || '2Captcha'} key: (not set)`;
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

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.CaptchaPanel = CaptchaPanel;

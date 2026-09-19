/* captcha.js — standalone Captcha window: 2Captcha auto-solve control.
   Key stays local (config/2captcha.json, git-ignored); the UI only ever
   receives the masked form (RULE 20). The raw key is cleared from the
   field after a successful save and is never kept in a page preset. */
'use strict';

const CaptchaPanel = {
  init() {
    document.getElementById('captchaSaveBtn')?.addEventListener('click', () => this.save());
    document.getElementById('captchaStatsBtn')?.addEventListener('click', () => this.loadStats());
    document.getElementById('captchaKeyShow')?.addEventListener('change', (e) => {
      const k = document.getElementById('captchaApiKey');
      if (k) k.type = e.target.checked ? 'text' : 'password';
    });
    setTimeout(() => this.loadStatus(), 1200);
    setTimeout(() => this.loadStats(), 1400);
  },

  _applyStatusValues(r) {
    const en = document.getElementById('captchaEnabled');
    if (en) en.checked = r.enabled !== false;
    const setVal = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== null) el.value = v; };
    setVal('captchaTimeoutMin', Math.round(((r.solve_timeout_sec || 180) / 60) * 10) / 10);
  },

  loadStatus() {
    if (!App.bridge?.get_captcha_status) return;
    App.bridge.get_captcha_status((res) => {
      try {
        const r = JSON.parse(res);
        if (!r.ok) return;
        this._applyStatusValues(r);
        this.renderStatus(r);
      } catch (e) {}
    });
  },

  _modeText(enabled) {
    return enabled ? 'auto-solve: ON (2Captcha will solve visible captchas)' : 'auto-solve: OFF (app waits for your manual solve)';
  },

  _balanceText(r) {
    if (r.balance === null || r.balance === undefined) return 'balance: —';
    const suffix = r.balance_at ? ` (checked ${r.balance_at})` : '';
    return `balance: $${Number(r.balance).toFixed(2)}${suffix}`;
  },

  renderStatus(r) {
    const line = document.getElementById('captchaStatusLine');
    if (!line) return;
    const mode = this._modeText(r.enabled);
    const key = r.has_key ? `key: ${r.masked_key || '****'}` : 'key: (not set)';
    const bal = this._balanceText(r);
    const err = r.last_error ? ` · last error: ${r.last_error}` : '';
    line.textContent = `${mode} · ${key} · ${bal}${err}`;
    if (r.balance !== null && r.balance !== undefined) {
      const b = document.getElementById('capStatBalance');
      if (b) b.textContent = `$${Number(r.balance).toFixed(2)}`;
    }
  },

  _buildPayload() {
    const en = document.getElementById('captchaEnabled');
    const key = (document.getElementById('captchaApiKey')?.value || '').trim();
    const min = parseFloat(document.getElementById('captchaTimeoutMin')?.value);
    const timeoutSec = Math.round((isNaN(min) ? 3 : min) * 60);
    return {enabled: en ? en.checked : false, api_key: key, solve_timeout_sec: timeoutSec};
  },

  _onSaveRes(res) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        LogConsole.log(`2Captcha saved: ${r.enabled ? 'enabled' : 'disabled'}, key=${r.masked_key || '(empty)'}`, 'success');
        const k = document.getElementById('captchaApiKey');
        if (k) k.value = '';
        this.loadStatus();
        this.loadStats();
      } else {
        LogConsole.log('2Captcha save failed: ' + (r.error || '?'), 'error');
      }
    } catch (e) {}
  },

  save() {
    if (!App.bridge?.set_captcha_settings) return;
    const payload = this._buildPayload();
    App.bridge.set_captcha_settings(JSON.stringify(payload), (res) => this._onSaveRes(res));
  },

  loadStats() {
    if (!App.bridge?.get_captcha_stats) return;
    App.bridge.get_captcha_stats((res) => {
      try {
        const r = JSON.parse(res);
        if (!r.ok) return;
        this.renderStats(r);
      } catch (e) {}
    });
  },

  renderStats(r) {
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('capStatDetected', r.detected_total ?? 0);
    set('capStatAuto', r.auto_solved ?? 0);
    set('capStatFailed', r.auto_failed ?? 0);
    const denom = (r.auto_solved ?? 0) + (r.auto_failed ?? 0);
    set('capStatRate', denom ? `${Math.round((r.auto_solved / denom) * 100)}% (${r.auto_solved}/${denom})` : '—');
    set('capStatManual', r.manual_solved ?? 0);
    if (r.last_balance !== null && r.last_balance !== undefined) {
      set('capStatBalance', `$${Number(r.last_balance).toFixed(2)}`);
    }
  },
};

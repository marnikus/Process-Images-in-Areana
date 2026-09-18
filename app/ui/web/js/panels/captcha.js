/* captcha.js — standalone Captcha window: solver-provider auto-solve control.
   Two providers (2Captcha, CapMonster Cloud) share the window; enable + API
   key are PER PROVIDER, the timeout is shared. Keys stay local
   (config/captcha_solvers.json, git-ignored); the UI only ever receives the
   masked form (RULE 20). The raw key is cleared from the field after a
   successful save and is never kept in a page preset. */
'use strict';

const CAPTCHA_PROVIDER_TITLES = { '2captcha': '2Captcha', 'capmonster': 'CapMonster Cloud' };

const CaptchaPanel = {
  init() {
    document.getElementById('captchaSaveBtn')?.addEventListener('click', () => this.save());
    document.getElementById('captchaStatsBtn')?.addEventListener('click', () => this.loadStats());
    document.getElementById('captchaKeyShow')?.addEventListener('change', (e) => {
      const k = document.getElementById('captchaApiKey');
      if (k) k.type = e.target.checked ? 'text' : 'password';
    });
    document.getElementById('captchaProvider')?.addEventListener('change', () => {
      const k = document.getElementById('captchaApiKey');
      if (k) k.value = '';  // never carry one provider's field into the other's
      this.loadStatus();
    });
    setTimeout(() => this.loadStatus(), 1200);
    setTimeout(() => this.loadStats(), 1400);
  },

  providerTitle(pid) {
    return CAPTCHA_PROVIDER_TITLES[pid] || pid || '2Captcha';
  },

  loadStatus() {
    if (App.bridge && App.bridge.get_captcha_status) {
      App.bridge.get_captcha_status((res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) return;
          const en = document.getElementById('captchaEnabled');
          if (en) en.checked = r.enabled !== false;
          const sel = document.getElementById('captchaProvider');
          if (sel && r.provider && CAPTCHA_PROVIDER_TITLES[r.provider]) sel.value = r.provider;
          const setVal = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== null) el.value = v; };
          setVal('captchaTimeoutMin', Math.round(((r.solve_timeout_sec || 180) / 60) * 10) / 10);
          this.renderStatus(r);
        } catch (e) {}
      });
    }
  },

  renderStatus(r) {
    const line = document.getElementById('captchaStatusLine');
    if (!line) return;
    const title = this.providerTitle(r.provider);
    const mode = r.enabled ? `auto-solve: ON (${title} will solve visible captchas)` : 'auto-solve: OFF (app waits for your manual solve)';
    const key = r.has_key ? `key: ${r.masked_key || '****'}` : 'key: (not set)';
    const bal = r.balance !== null && r.balance !== undefined ? `balance: $${Number(r.balance).toFixed(2)}${r.balance_at ? ` (checked ${r.balance_at})` : ''}` : 'balance: —';
    const err = r.last_error ? ` · last error: ${r.last_error}` : '';
    line.textContent = `${mode} · ${key} · ${bal}${err}`;
    if (r.balance !== null && r.balance !== undefined) {
      const b = document.getElementById('capStatBalance');
      if (b) b.textContent = `$${Number(r.balance).toFixed(2)}`;
    }
  },

  save() {
    const en = document.getElementById('captchaEnabled');
    const provider = document.getElementById('captchaProvider')?.value || '2captcha';
    const key = (document.getElementById('captchaApiKey')?.value || '').trim();
    const min = parseFloat(document.getElementById('captchaTimeoutMin')?.value);
    const timeoutSec = Math.round((isNaN(min) ? 3 : min) * 60);
    const payload = {provider, enabled: en ? en.checked : false, api_key: key, solve_timeout_sec: timeoutSec};
    if (App.bridge && App.bridge.set_captcha_settings) {
      App.bridge.set_captcha_settings(JSON.stringify(payload), (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`${this.providerTitle(r.provider)} saved: ${r.enabled ? 'enabled' : 'disabled'}, key=${r.masked_key || '(empty)'}`, 'success');
            document.getElementById('captchaApiKey').value = '';  // don't keep the raw key in the field
            this.loadStatus();
            this.loadStats();
          } else {
            LogConsole.log('Captcha solver save failed: ' + (r.error || '?'), 'error');
          }
        } catch (e) {}
      });
    }
  },

  loadStats() {
    if (App.bridge && App.bridge.get_captcha_stats) {
      App.bridge.get_captcha_stats((res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) return;
          this.renderStats(r);
        } catch (e) {}
      });
    }
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

/* captcha.js — standalone Captcha window: solver-provider auto-solve control.
   Two providers (2Captcha, CapMonster Cloud) share the window; enable + API
   key are PER PROVIDER, the timeout is shared. The provider drop-down is
   user-owned: picking a provider never reverts — not on reload, not on a
   failed balance check (RULE 4: report what is missing, never silently undo
   the user's choice). The selection + key are stored by Save, which also
   commits the active provider. Keys stay local (config/captcha_solvers.json,
   git-ignored); the UI only ever receives the masked form (RULE 20). The raw
   key is cleared from the field after a successful save. */
'use strict';

const CAPTCHA_PROVIDER_TITLES = { '2captcha': '2Captcha', 'capmonster': 'CapMonster Cloud' };

const CaptchaPanel = {
  _lastStatus: null,       // last get_captcha_status payload (masked only)
  _providerTouched: false, // user changed the drop-down — reloads must not re-sync it

  init() {
    document.getElementById('captchaSaveBtn')?.addEventListener('click', () => this.save());
    document.getElementById('captchaStatsBtn')?.addEventListener('click', () => this.loadStats());
    document.getElementById('captchaKeyShow')?.addEventListener('change', (e) => {
      const k = document.getElementById('captchaApiKey');
      if (k) k.type = e.target.checked ? 'text' : 'password';
    });
    document.getElementById('captchaProvider')?.addEventListener('change', () => this.onProviderChange());
    setTimeout(() => this.loadStatus(), 1200);
    setTimeout(() => this.loadStats(), 1400);
  },

  providerTitle(pid) {
    return CAPTCHA_PROVIDER_TITLES[pid] || pid || '2Captcha';
  },

  selectedProvider() {
    return document.getElementById('captchaProvider')?.value || '2captcha';
  },

  onProviderChange() {
    /* Switching is always allowed — with or without a key saved. */
    this._providerTouched = true;
    const k = document.getElementById('captchaApiKey');
    if (k) k.value = '';  // never carry one provider's field into the other's
    const en = document.getElementById('captchaEnabled');
    if (en) en.checked = this.providerState(this._lastStatus || {}, this.selectedProvider()).enabled;
    this.renderStatus(this._lastStatus || {});
  },

  providerState(r, pid) {
    /* Per-provider view for the status line; falls back to the active fields
       for payloads stored before the multi-provider key store existed. */
    const p = (r && r.providers && r.providers[pid]) || null;
    if (p) return p;
    if (r && r.provider === pid) return r;
    return { enabled: false, has_key: false, masked_key: '' };
  },

  loadStatus() {
    if (App.bridge && App.bridge.get_captcha_status) {
      App.bridge.get_captcha_status((res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) return;
          this._lastStatus = r;
          const sel = document.getElementById('captchaProvider');
          if (sel && !this._providerTouched && r.provider && CAPTCHA_PROVIDER_TITLES[r.provider]) {
            sel.value = r.provider;  // initial sync only — never after a user change
          }
          const en = document.getElementById('captchaEnabled');
          if (en) en.checked = this.providerState(r, this.selectedProvider()).enabled;
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
    const pid = this.selectedProvider();
    const state = this.providerState(r, pid);
    const title = this.providerTitle(pid);
    const pending = r.provider && pid !== r.provider ? ' · press Save to switch' : '';
    const mode = state.enabled ? `auto-solve: ON (${title} will solve visible captchas)` : 'auto-solve: OFF (app waits for your manual solve)';
    const key = state.has_key ? `key: ${state.masked_key || '****'}` : 'key: (not set)';
    const mine = r.provider === pid;  // balance/error belong to the provider they were fetched from
    const bal = mine && r.balance !== null && r.balance !== undefined
      ? `balance: $${Number(r.balance).toFixed(2)}${r.balance_at ? ` (checked ${r.balance_at})` : ''}` : 'balance: —';
    const err = mine && r.last_error ? ` · last error: ${r.last_error}` : '';
    line.textContent = `${title} · ${mode} · ${key} · ${bal}${err}${pending}`;
    if (mine && r.balance !== null && r.balance !== undefined) {
      const b = document.getElementById('capStatBalance');
      if (b) b.textContent = `$${Number(r.balance).toFixed(2)}`;
    }
  },

  save() {
    const en = document.getElementById('captchaEnabled');
    const provider = this.selectedProvider();
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
            if (en && en.checked && !r.enabled) {
              LogConsole.log(`${this.providerTitle(r.provider)}: enable needs an API key — provider selection saved, paste a key and save again`, 'warn');
            }
            document.getElementById('captchaApiKey').value = '';  // don't keep the raw key in the field
            this._providerTouched = false;  // stored state now matches the selection
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

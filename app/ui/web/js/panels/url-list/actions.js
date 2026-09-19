/* url-list/actions.js — CRUD + cooldown + connect, ≤200 LOC, CC≤10 */
'use strict';
window.UrlListActions = {
  _store() { return window.UrlListStore; },
  _bridge() { return window.App && window.App.bridge; },

  addUrl() {
    const input = document.getElementById('urlInput');
    const val = input ? input.value.trim() : '';
    if (!val) return;
    const b = this._bridge();
    if (b && b.add_url) b.add_url(val, (res)=> this._onAdd(input, val, res));
  },

  _onAdd(input, val, res) {
    try {
      const r = JSON.parse(res);
      if (!r.ok) LogConsole.log('Add URL failed: ' + r.error, 'error');
      else {
        input.value = '';
        LogConsole.log('URL added: ' + val, 'success');
        if (typeof ArenaHistory !== 'undefined') setTimeout(()=>ArenaHistory.recordGlobal('urls', window.App.state.urls), 100);
      }
    } catch {}
  },

  removeUrl(id) {
    const b = this._bridge();
    if (b && b.remove_url) b.remove_url(id, () => LogConsole.log('URL removed', 'info'));
  },

  toggleUrl(id) {
    const b = this._bridge();
    if (b && b.toggle_url) b.toggle_url(id, () => {});
  },

  testUrl(id) {
    const b = this._bridge();
    if (!b || !b.test_url) return;
    LogConsole.log('Testing URL ' + id + '...', 'info');
    b.test_url(id, (res) => {
      try { const r=JSON.parse(res); LogConsole.log('Test result: '+(r.ok?'OK':r.error), r.ok?'success':'error'); } catch {}
    });
  },

  editUrl(id) {
    const row = this._store().snapshotUrls().find(u => String(u.id) === String(id));
    const current = row ? row.url : '';
    const apply = (newUrl) => this._applyEdit(id, newUrl);
    if (window.Dialog && window.Dialog.promptEdit) {
      window.Dialog.promptEdit('Edit URL', current || 'https://…', 'Save', apply);
      return;
    }
    const typed = typeof prompt === 'function' ? prompt('Edit URL:', current) : null;  // standalone fallback
    if (typed) apply(typed);
  },

  _applyEdit(id, newUrl) {
    const b = this._bridge();
    if (!b || !b.edit_url) { LogConsole.log('Edit failed: bridge slot edit_url missing', 'error'); return; }
    b.edit_url(id, newUrl, (res) => {
      try {
        const r = JSON.parse(res);
        if (!r.ok) { LogConsole.log('Edit failed: ' + r.error, 'error'); return; }
        LogConsole.log('URL updated: ' + (r.url || newUrl), 'success');
        if (typeof ArenaHistory !== 'undefined') setTimeout(() => ArenaHistory.recordGlobal('urls', window.App.state.urls), 100);
      } catch {}
    });
  },

  connectUrl(id) {
    const urlObj = this._store().snapshotUrls().find(u => u.id === id);
    let url = urlObj ? urlObj.url : '';
    if (!url) { LogConsole.log('⚠ URL not found', 'warn'); return; }
    url = this._store().extractUrl(url);
    if (this._store().shouldDebounce(url)) return;
    LogConsole.log(`🔍 Connect: finding tab for ${url}`, 'info');
    const b = this._bridge();
    if (b && b.find_tab_by_url) b.find_tab_by_url(url);
    const inp = document.getElementById('urlBookmarkInput');
    if (inp) inp.value = url;
  },

  stopJob(urlId) {
    const u = this._store().snapshotUrls().find(x => String(x.id) === String(urlId));
    const tab = u ? u.tab_id : null;
    if (!tab) { LogConsole.log('Stop: row has no linked tab yet', 'warn'); return; }
    const b = this._bridge();
    if (b && b.stop_tab_job) b.stop_tab_job(tab, (res)=> this._onStop(tab, res));
  },

  _onStop(tab, res) {
    try {
      const r = JSON.parse(res);
      LogConsole.log(r.ok ? `⛔ Stop requested for tab ${String(tab).slice(0,8)}` : 'Stop: '+(r.error||'failed'), r.ok?'warn':'error');
    } catch { LogConsole.log('Stop failed','error'); }
  },

  coolAction(action, btn) {
    const tabId = btn.dataset.tabId;
    if (!tabId) { LogConsole.log('⚠ Tab not in pool — Connect it, then add to pool first', 'warn'); return; }
    if (typeof PagePoolPanel === 'undefined') return;
    if (action === 'cool-reset') PagePoolPanel.resetCooldown(tabId);
    else PagePoolPanel.editCooldown(tabId);
  },

  reparseTabs() {
    LogConsole.log('🔄 Reparse requested — scanning open tabs…', 'info');
    const b = this._bridge();
    if (b && b.auto_connect_scan) b.auto_connect_scan('manual');
  },

  popupTabs() {
    const b = this._bridge();
    if (b && b.popup_url_tabs) b.popup_url_tabs();
  },

  _applyCooldownConfig(c) {
    const en = document.getElementById('urlCooldownEnabled');
    if (en) en.checked = c.enabled !== false;
    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    setVal('urlCooldownMin', c.min_minutes ?? Math.round((c.min_seconds||300)/60));
    setVal('urlCooldownPenalty', c.captcha_penalty_minutes ?? Math.round((c.captcha_penalty_seconds||900)/60));
    setVal('urlCooldownRateLimit', c.rate_limit_penalty_minutes ?? Math.round((c.rate_limit_penalty_seconds||1800)/60));
  },

  loadCooldownConfig() {
    const b = this._bridge();
    if (!b || !b.get_cooldown_config) return;
    b.get_cooldown_config((res)=>{
      try {
        const r=JSON.parse(res);
        if (!r.ok||!r.config) return;
        this._applyCooldownConfig(r.config);
      } catch {}
    });
  },

  _readCooldownInputs() {
    const en = document.getElementById('urlCooldownEnabled');
    const getNum = (id, fb) => { const el = document.getElementById(id); const v = el ? parseFloat(el.value) : NaN; return isNaN(v) ? fb : v; };
    const minM = Math.max(0, Math.min(1440, getNum('urlCooldownMin',5)));
    const penM = Math.max(0, Math.min(1440, getNum('urlCooldownPenalty',15)));
    const rlM = Math.max(0, Math.min(1440, getNum('urlCooldownRateLimit',30)));
    return { en, minM, penM, rlM };
  },

  saveCooldownConfig() {
    const inputs = this._readCooldownInputs();
    const payload = { enabled: inputs.en?inputs.en.checked:true, min_seconds:Math.round(inputs.minM*60), captcha_penalty_seconds:Math.round(inputs.penM*60), rate_limit_penalty_seconds:Math.round(inputs.rlM*60) };
    const b = this._bridge();
    if (b && b.set_cooldown_config) b.set_cooldown_config(JSON.stringify(payload),(res)=> this._onSaveCooldown(inputs, res));
  },

  _onSaveCooldown(inputs, res) {
    try {
      const r=JSON.parse(res);
      const msg = r.ok ? `Cooldown saved: ${inputs.en&&inputs.en.checked?'on':'off'} pause=${inputs.minM}m captcha=+${inputs.penM}m limit=+${inputs.rlM}m` : 'Cooldown save failed: '+r.error;
      LogConsole.log(msg, r.ok?'success':'error');
    } catch {}
  },
};

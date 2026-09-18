/* settings.js — including CDP host/port/user-data-dir user configurable */
'use strict';

const SettingsPanel = {
  cdpConfig: {host: '127.0.0.1', port: 9222, user_data_dir: 'C:\\arena-images-chrome', extra_args: '', url_pattern: 'arena.ai'},

  init() {
    document.getElementById('settingsSaveBtn')?.addEventListener('click', ()=>this.save());
    document.getElementById('settingsExportBtn')?.addEventListener('click', ()=>this.exportPreset());
    document.getElementById('settingsImportBtn')?.addEventListener('click', ()=>this.importPreset());

    // CDP config save button
    document.getElementById('cdpSaveBtn')?.addEventListener('click', ()=>this.saveCDP());
    document.getElementById('cdpTestBtn')?.addEventListener('click', ()=>this.testCDP());
    document.getElementById('cdpCopyCmdBtn')?.addEventListener('click', ()=>this.copyChromeCmd());

    // 2Captcha solving panel
    document.getElementById('captchaSaveBtn')?.addEventListener('click', ()=>this.saveCaptcha());
    document.getElementById('captchaStatsBtn')?.addEventListener('click', ()=>this.loadCaptchaStats());
    document.getElementById('captchaKeyShow')?.addEventListener('change', (e)=>{
      const k = document.getElementById('captchaApiKey');
      if (k) k.type = e.target.checked ? 'text' : 'password';
    });

    // load CDP config on init
    setTimeout(()=>this.loadCDPConfig(), 1000);
    setTimeout(()=>this.loadCooldownConfig(), 1200);
    setTimeout(()=>this.loadCaptchaStatus(), 1400);
    setTimeout(()=>this.loadCaptchaStats(), 1600);
  },

  restore(state) {
    if (!state || !state.settings) return;
    const s = state.settings;
    const setVal = (id, v) => { const el=document.getElementById(id); if(el) el.value=v; };
    setVal('setTimeout', s.timeout_seconds || 120);
    setVal('setGenerationTimeout', s.generation_timeout || s.timeouts?.generation || 120);
    setVal('setRetries', s.max_retries || 3);
    setVal('setNaming', s.naming_suffix || '_AI');
    setVal('setFileTypes', (s.supported_types||[]).join(','));
    setVal('setOverwrite', s.overwrite ? 'true' : 'false');
    setVal('setHighlightDur', s.highlight_duration || 3);
    setVal('setMaxConcurrent', s.max_concurrent || 1);
  },

  loadCDPConfig() {
    if (App.bridge && App.bridge.get_cdp_config) {
      App.bridge.get_cdp_config((res)=>{
        try {
          const cfg = JSON.parse(res);
          if (cfg.error) return;
          this.cdpConfig = cfg;
          const setVal = (id, v) => { const el=document.getElementById(id); if(el) el.value=v; };
          setVal('cdpHost', cfg.host || '127.0.0.1');
          setVal('cdpPort', cfg.port || 9222);
          setVal('cdpUserDataDir', cfg.user_data_dir || 'C:\\arena-images-chrome');
          setVal('cdpExtraArgs', cfg.extra_args || '');
          setVal('cdpUrlPattern', (cfg.url_pattern === undefined || cfg.url_pattern === null) ? 'arena.ai' : cfg.url_pattern);
          this.updateChromeCmdPreview();
          // also update toolbar
          if (typeof CDPPanel !== 'undefined' && CDPPanel.updateChromeToolbar) {
            CDPPanel.updateChromeToolbar(cfg);
          }
        } catch(e){}
      });
    }
    // also get launch command
    if (App.bridge && App.bridge.get_chrome_launch_command) {
      App.bridge.get_chrome_launch_command((res)=>{
        try {
          const cmd = JSON.parse(res);
          const el = document.getElementById('cdpLaunchCmd');
          if (el) el.textContent = cmd.windows || '';
        } catch{}
      });
    }
  },

  updateChromeCmdPreview() {
    const host = document.getElementById('cdpHost')?.value || '127.0.0.1';
    const port = document.getElementById('cdpPort')?.value || 9222;
    const dir = document.getElementById('cdpUserDataDir')?.value || 'C:\\arena-images-chrome';
    const extra = document.getElementById('cdpExtraArgs')?.value || '';
    let cmd = `"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=${port} --user-data-dir="${dir}"`;
    if (extra) cmd += ` ${extra}`;
    const el = document.getElementById('cdpLaunchCmd');
    if (el) el.textContent = cmd;
    const testEl = document.getElementById('cdpTestUrl');
    if (testEl) testEl.textContent = `http://${host}:${port}/json/list`;
    if (typeof CDPPanel !== 'undefined') {
      if (CDPPanel.updateChromeToolbar) CDPPanel.updateChromeToolbar({host, port, user_data_dir: dir, extra_args: extra});
      CDPPanel.currentConfig = {host, port: parseInt(port)||9222, user_data_dir: dir, extra_args: extra};
    }
  },

  save() {
    const getVal = (id) => document.getElementById(id)?.value;
    const genTo = parseInt(getVal('setGenerationTimeout'))||120;
    const payload = {
      timeout_seconds: parseInt(getVal('setTimeout'))||120,
      generation_timeout: genTo,
      max_retries: parseInt(getVal('setRetries'))||3,
      naming_suffix: getVal('setNaming')||'_AI',
      supported_types: (getVal('setFileTypes')||'.png,.jpg').split(',').map(x=>x.trim()).filter(Boolean),
      overwrite: getVal('setOverwrite')==='true',
      highlight_duration: parseInt(getVal('setHighlightDur'))||3,
      max_concurrent: parseInt(getVal('setMaxConcurrent'))||1,
      watcher_generation_timeout_sec: genTo, // sync to watcher win setting (user timeout from win)
    };
    if (App.bridge && App.bridge.save_settings) {
      App.bridge.save_settings(JSON.stringify(payload), (res)=>{
        try{
          const r=JSON.parse(res);
          LogConsole.log(r.ok?`Settings saved — generation timeout ${genTo}s synced to watcher win`:'Save failed: '+r.error, r.ok?'success':'error');
          // Also update watcher panel UI if exists
          if (r.ok && typeof WatcherPanel !== 'undefined') {
            WatcherPanel.config.generation_timeout_sec = genTo;
            const el = document.getElementById('watcherGenerationTimeout');
            if (el) el.value = genTo;
          }
        }catch(e){}
      });
    }
    // also save CDP if changed
    this.saveCDP();
    this.saveCooldown();
  },

  loadCooldownConfig() {
    if (App.bridge && App.bridge.get_cooldown_config) {
      App.bridge.get_cooldown_config((res)=>{
        try {
          const r = JSON.parse(res);
          if (!r.ok || !r.config) return;
          const c = r.config;
          const en = document.getElementById('cooldownEnabled');
          if (en) en.checked = c.enabled !== false;
          const setVal = (id, v) => { const el=document.getElementById(id); if(el) el.value=v; };
          setVal('cooldownMinMinutes', c.min_minutes ?? Math.round((c.min_seconds||300)/60));
          setVal('cooldownCaptchaMinutes', c.captcha_penalty_minutes ?? Math.round((c.captcha_penalty_seconds||900)/60));
        } catch(e){}
      });
    }
  },

  saveCooldown() {
    const en = document.getElementById('cooldownEnabled');
    const getNum = (id, fb) => { const v = parseFloat(document.getElementById(id)?.value); return isNaN(v) ? fb : v; };
    const enabled = en ? en.checked : true;
    const minM = Math.max(0, Math.min(1440, getNum('cooldownMinMinutes', 5)));
    const penM = Math.max(0, Math.min(1440, getNum('cooldownCaptchaMinutes', 15)));
    const payload = {enabled, min_seconds: Math.round(minM*60), captcha_penalty_seconds: Math.round(penM*60)};
    if (App.bridge && App.bridge.set_cooldown_config) {
      App.bridge.set_cooldown_config(JSON.stringify(payload), (res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? `Cooldown saved: ${enabled?'on':'off'} min=${minM}m captcha=+${penM}m` : 'Cooldown save failed: '+r.error, r.ok?'success':'error');
        } catch(e){}
      });
    }
  },

  /* ---- 2Captcha solving — key stays local, UI only ever sees the masked form ---- */

  loadCaptchaStatus() {
    if (App.bridge && App.bridge.get_captcha_status) {
      App.bridge.get_captcha_status((res)=>{
        try {
          const r = JSON.parse(res);
          if (!r.ok) return;
          const en = document.getElementById('captchaEnabled');
          if (en) en.checked = r.enabled !== false;
          const setVal = (id, v) => { const el=document.getElementById(id); if(el && v!==undefined && v!==null) el.value=v; };
          setVal('captchaTimeoutMin', Math.round(((r.solve_timeout_sec||180)/60)*10)/10);
          this.renderCaptchaStatus(r);
        } catch(e){}
      });
    }
  },

  renderCaptchaStatus(r) {
    const line = document.getElementById('captchaStatusLine');
    if (!line) return;
    const key = r.has_key ? `key: ${r.masked_key||'****'}` : 'key: (not set)';
    const bal = r.balance!==null && r.balance!==undefined ? `balance: $${Number(r.balance).toFixed(2)}${r.balance_at?` (checked ${r.balance_at})`:''}` : 'balance: —';
    const err = r.last_error ? ` · last error: ${r.last_error}` : '';
    line.textContent = `${key} · ${bal}${err}`;
    if (typeof r.balance !== 'undefined' && r.balance !== null) {
      document.getElementById('capStatBalance').textContent = `$${Number(r.balance).toFixed(2)}`;
    }
  },

  saveCaptcha() {
    const en = document.getElementById('captchaEnabled');
    const key = (document.getElementById('captchaApiKey')?.value || '').trim();
    const min = parseFloat(document.getElementById('captchaTimeoutMin')?.value);
    const timeoutSec = Math.round((isNaN(min) ? 3 : min) * 60);
    const payload = {enabled: en ? en.checked : false, api_key: key, solve_timeout_sec: timeoutSec};
    if (App.bridge && App.bridge.set_captcha_settings) {
      App.bridge.set_captcha_settings(JSON.stringify(payload), (res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`2Captcha saved: ${r.enabled?'enabled':'disabled'}, key=${r.masked_key||'(empty)'}`, 'success');
            document.getElementById('captchaApiKey').value = '';  // don't keep the raw key in the field
            this.loadCaptchaStatus();
            this.loadCaptchaStats();
          } else {
            LogConsole.log('2Captcha save failed: '+(r.error||'?'), 'error');
          }
        } catch(e){}
      });
    }
  },

  loadCaptchaStats() {
    if (App.bridge && App.bridge.get_captcha_stats) {
      App.bridge.get_captcha_stats((res)=>{
        try {
          const r = JSON.parse(res);
          if (!r.ok) return;
          this.renderCaptchaStats(r);
        } catch(e){}
      });
    }
  },

  renderCaptchaStats(r) {
    const set = (id, v) => { const el=document.getElementById(id); if(el) el.textContent = v; };
    set('capStatDetected', r.detected_total ?? 0);
    set('capStatAuto', r.auto_solved ?? 0);
    set('capStatFailed', r.auto_failed ?? 0);
    const denom = (r.auto_solved ?? 0) + (r.auto_failed ?? 0);
    set('capStatRate', denom ? `${Math.round((r.auto_solved/denom)*100)}% (${r.auto_solved}/${denom})` : '—');
    set('capStatManual', r.manual_solved ?? 0);
    if (r.last_balance !== null && r.last_balance !== undefined) {
      set('capStatBalance', `$${Number(r.last_balance).toFixed(2)}`);
    }
  },

  saveCDP() {
    const getVal = (id) => document.getElementById(id)?.value;
    const host = (getVal('cdpHost')||'127.0.0.1').trim() || '127.0.0.1';
    let port = parseInt(getVal('cdpPort'))||9222;
    if (port < 1 || port > 65535) { LogConsole.log('⚠ Port must be 1-65535', 'warn'); return; }
    const user_data_dir = (getVal('cdpUserDataDir')||'C:\\arena-images-chrome').trim() || 'C:\\arena-images-chrome';
    const extra = (getVal('cdpExtraArgs')||'').trim();
    const url_pattern = (getVal('cdpUrlPattern')||'').trim();
    const payload = {host, port, user_data_dir, extra_args: extra, url_pattern};
    if (App.bridge && App.bridge.set_cdp_config) {
      App.bridge.set_cdp_config(JSON.stringify(payload), (res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`CDP config saved: ${host}:${port} dir=${user_data_dir} pattern='${url_pattern || '(all)'}' — restart Chrome with new command, then Diagnose`, 'success');
            this.cdpConfig = {host, port, user_data_dir, extra_args: extra, url_pattern};
            this.updateChromeCmdPreview();
          } else {
            LogConsole.log('Save CDP failed: '+r.error, 'error');
          }
        } catch(e){}
      });
    }
  },

  testCDP() {
    if (typeof CDPPanel !== 'undefined' && CDPPanel.diagnose) {
      CDPPanel.diagnose();
    } else if (App.bridge && App.bridge.diagnose_chrome) {
      App.bridge.diagnose_chrome((res)=>{
        try { const d=JSON.parse(res); LogConsole.log(d.summary||'diagnose done', 'info'); } catch{}
      });
    }
  },

  copyChromeCmd() {
    const el = document.getElementById('cdpLaunchCmd');
    const txt = el ? el.textContent : '';
    if (!txt) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(txt).then(()=>LogConsole.log('Chrome launch command copied', 'success'));
    } else {
      LogConsole.log('Copy: '+txt, 'info');
    }
  },

  exportPreset() {
    const nameEl = document.getElementById('presetNameInput');
    const name = nameEl?.value || 'preset_'+Date.now();
    if (App.bridge && App.bridge.export_preset) {
      App.bridge.export_preset(name, (res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Preset exported: '+r.path:'Export failed: '+r.error, r.ok?'success':'error'); }catch(e){}
      });
    }
  },

  importPreset() {
    if (App.bridge && App.bridge.import_preset) {
      App.bridge.import_preset((res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Preset imported':'Import failed: '+r.error, r.ok?'success':'error'); }catch(e){}
      });
    }
  }
};

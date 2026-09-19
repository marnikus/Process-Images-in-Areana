/* settings.js — CDP + cooldown + general settings, RULE18 file 150-300, CC≤10 via helpers */
'use strict';

const SettingsPanel = {
  cdpConfig: {host: '127.0.0.1', port: 9222, user_data_dir: 'C:\\arena-images-chrome', extra_args: '', url_pattern: 'arena.ai'},

  init() {
    document.getElementById('settingsSaveBtn')?.addEventListener('click', ()=>this.save());
    document.getElementById('settingsExportBtn')?.addEventListener('click', ()=>this.exportPreset());
    document.getElementById('settingsImportBtn')?.addEventListener('click', ()=>this.importPreset());
    document.getElementById('cdpSaveBtn')?.addEventListener('click', ()=>this.saveCDP());
    document.getElementById('cdpTestBtn')?.addEventListener('click', ()=>this.testCDP());
    document.getElementById('cdpCopyCmdBtn')?.addEventListener('click', ()=>this.copyChromeCmd());
    setTimeout(()=>this.loadCDPConfig(), 1000);
    setTimeout(()=>this.loadCooldownConfig(), 1200);
  },

  _setVal(id, v) {
    const el=document.getElementById(id);
    if (el) el.value=v;
  },

  restore(state) {
    if (!state) return;
    if (!state.settings) return;
    const s = state.settings;
    this._applySettings(s);
  },

  _getOr(s, key, fallback) {
    const v = s[key];
    if (v === undefined || v === null || v === '') return fallback;
    return v;
  },

  _applySettings(s) {
    this._setVal('setTimeout', this._getOr(s, 'timeout_seconds', 120));
    let gen = s.generation_timeout;
    if (!gen && s.timeouts) gen = s.timeouts.generation;
    if (!gen) gen = 120;
    this._setVal('setGenerationTimeout', gen);
    this._setVal('setRetries', this._getOr(s, 'max_retries', 3));
    this._setVal('setNaming', this._getOr(s, 'naming_suffix', '_AI'));
    const ft = s.supported_types;
    this._setVal('setFileTypes', ft && ft.join ? ft.join(',') : '');
    let ow = 'false';
    if (s.overwrite) ow = 'true';
    this._setVal('setOverwrite', ow);
    this._setVal('setHighlightDur', this._getOr(s, 'highlight_duration', 3));
    this._setVal('setMaxConcurrent', this._getOr(s, 'max_concurrent', 1));
  },

  _applyCDPConfig(cfg) {
    this.cdpConfig = cfg;
    this._setVal('cdpHost', cfg.host || '127.0.0.1');
    this._setVal('cdpPort', cfg.port || 9222);
    this._setVal('cdpUserDataDir', cfg.user_data_dir || 'C:\\arena-images-chrome');
    this._setVal('cdpExtraArgs', cfg.extra_args || '');
    this._setVal('cdpUrlPattern', (cfg.url_pattern === undefined || cfg.url_pattern === null) ? 'arena.ai' : cfg.url_pattern);
    this.updateChromeCmdPreview();
    if (typeof CDPPanel !== 'undefined' && CDPPanel.updateChromeToolbar) CDPPanel.updateChromeToolbar(cfg);
  },

  _onCDPConfig(res) {
    try {
      const cfg = JSON.parse(res);
      if (cfg.error) return;
      this._applyCDPConfig(cfg);
    } catch(e){}
  },

  _onLaunchCmd(res) {
    try {
      const cmd = JSON.parse(res);
      const el = document.getElementById('cdpLaunchCmd');
      if (el) el.textContent = cmd.windows || '';
    } catch{}
  },

  loadCDPConfig() {
    if (App.bridge?.get_cdp_config) App.bridge.get_cdp_config((res)=> this._onCDPConfig(res));
    if (App.bridge?.get_chrome_launch_command) App.bridge.get_chrome_launch_command((res)=> this._onLaunchCmd(res));
  },

  _buildChromeCmd(host, port, dir, extra) {
    let cmd = `"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=${port} --user-data-dir="${dir}"`;
    if (extra) cmd += ` ${extra}`;
    return cmd;
  },

  updateChromeCmdPreview() {
    const host = document.getElementById('cdpHost')?.value || '127.0.0.1';
    const port = document.getElementById('cdpPort')?.value || 9222;
    const dir = document.getElementById('cdpUserDataDir')?.value || 'C:\\arena-images-chrome';
    const extra = document.getElementById('cdpExtraArgs')?.value || '';
    const el = document.getElementById('cdpLaunchCmd');
    if (el) el.textContent = this._buildChromeCmd(host, port, dir, extra);
    const testEl = document.getElementById('cdpTestUrl');
    if (testEl) testEl.textContent = `http://${host}:${port}/json/list`;
    if (typeof CDPPanel !== 'undefined') {
      if (CDPPanel.updateChromeToolbar) CDPPanel.updateChromeToolbar({host, port, user_data_dir: dir, extra_args: extra});
      CDPPanel.currentConfig = {host, port: parseInt(port)||9222, user_data_dir: dir, extra_args: extra};
    }
  },

  _buildSettingsPayload() {
    const getVal = (id) => document.getElementById(id)?.value;
    const genTo = parseInt(getVal('setGenerationTimeout'))||120;
    return {
      payload: {
        timeout_seconds: parseInt(getVal('setTimeout'))||120,
        generation_timeout: genTo,
        max_retries: parseInt(getVal('setRetries'))||3,
        naming_suffix: getVal('setNaming')||'_AI',
        supported_types: (getVal('setFileTypes')||'.png,.jpg').split(',').map(x=>x.trim()).filter(Boolean),
        overwrite: getVal('setOverwrite')==='true',
        highlight_duration: parseInt(getVal('setHighlightDur'))||3,
        max_concurrent: parseInt(getVal('setMaxConcurrent'))||1,
        watcher_generation_timeout_sec: genTo,
      },
      genTo,
    };
  },

  _onSaveSettings(res, genTo) {
    try{
      const r=JSON.parse(res);
      LogConsole.log(r.ok?`Settings saved — generation timeout ${genTo}s synced to watcher win`:'Save failed: '+r.error, r.ok?'success':'error');
      if (r.ok && typeof WatcherPanel !== 'undefined') {
        WatcherPanel.config.generation_timeout_sec = genTo;
        const el = document.getElementById('watcherGenerationTimeout');
        if (el) el.value = genTo;
      }
    }catch(e){}
  },

  save() {
    const { payload, genTo } = this._buildSettingsPayload();
    if (App.bridge?.save_settings) App.bridge.save_settings(JSON.stringify(payload), (res)=> this._onSaveSettings(res, genTo));
    this.saveCDP();
    this.saveCooldown();
  },

  _onCooldownConfig(res) {
    try {
      const r = JSON.parse(res);
      if (!r.ok || !r.config) return;
      const c = r.config;
      const en = document.getElementById('cooldownEnabled');
      if (en) en.checked = c.enabled !== false;
      this._setVal('cooldownMinMinutes', c.min_minutes ?? Math.round((c.min_seconds||300)/60));
      this._setVal('cooldownCaptchaMinutes', c.captcha_penalty_minutes ?? Math.round((c.captcha_penalty_seconds||900)/60));
    } catch(e){}
  },

  loadCooldownConfig() {
    if (App.bridge?.get_cooldown_config) App.bridge.get_cooldown_config((res)=> this._onCooldownConfig(res));
  },

  _readCooldownInputs() {
    const en = document.getElementById('cooldownEnabled');
    const getNum = (id, fb) => { const v = parseFloat(document.getElementById(id)?.value); return isNaN(v) ? fb : v; };
    const enabled = en ? en.checked : true;
    const minM = Math.max(0, Math.min(1440, getNum('cooldownMinMinutes', 5)));
    const penM = Math.max(0, Math.min(1440, getNum('cooldownCaptchaMinutes', 15)));
    return { enabled, minM, penM };
  },

  _onSaveCooldown(res, enabled, minM, penM) {
    try {
      const r = JSON.parse(res);
      LogConsole.log(r.ok ? `Cooldown saved: ${enabled?'on':'off'} min=${minM}m captcha=+${penM}m` : 'Cooldown save failed: '+r.error, r.ok?'success':'error');
    } catch(e){}
  },

  saveCooldown() {
    const { enabled, minM, penM } = this._readCooldownInputs();
    const payload = {enabled, min_seconds: Math.round(minM*60), captcha_penalty_seconds: Math.round(penM*60)};
    if (App.bridge?.set_cooldown_config) App.bridge.set_cooldown_config(JSON.stringify(payload), (res)=> this._onSaveCooldown(res, enabled, minM, penM));
  },

  _buildCDPPayload() {
    const getVal = (id) => document.getElementById(id)?.value;
    const host = (getVal('cdpHost')||'127.0.0.1').trim() || '127.0.0.1';
    let port = parseInt(getVal('cdpPort'))||9222;
    const user_data_dir = (getVal('cdpUserDataDir')||'C:\\arena-images-chrome').trim() || 'C:\\arena-images-chrome';
    const extra = (getVal('cdpExtraArgs')||'').trim();
    const url_pattern = (getVal('cdpUrlPattern')||'').trim();
    return { host, port, user_data_dir, extra_args: extra, url_pattern };
  },

  _onSaveCDP(res, payload) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        LogConsole.log(`CDP config saved: ${payload.host}:${payload.port} dir=${payload.user_data_dir} pattern='${payload.url_pattern || '(all)'}'`, 'success');
        this.cdpConfig = payload;
        this.updateChromeCmdPreview();
      } else {
        LogConsole.log('Save CDP failed: '+r.error, 'error');
      }
    } catch(e){}
  },

  saveCDP() {
    const payload = this._buildCDPPayload();
    if (payload.port < 1 || payload.port > 65535) { LogConsole.log('⚠ Port must be 1-65535', 'warn'); return; }
    if (App.bridge?.set_cdp_config) App.bridge.set_cdp_config(JSON.stringify(payload), (res)=> this._onSaveCDP(res, payload));
  },

  testCDP() {
    if (typeof CDPPanel !== 'undefined' && CDPPanel.diagnose) { CDPPanel.diagnose(); return; }
    if (App.bridge?.diagnose_chrome) {
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
    if (App.bridge?.export_preset) {
      App.bridge.export_preset(name, (res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Preset exported: '+r.path:'Export failed: '+r.error, r.ok?'success':'error'); }catch(e){}
      });
    }
  },

  importPreset() {
    if (App.bridge?.import_preset) {
      App.bridge.import_preset((res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Preset imported':'Import failed: '+r.error, r.ok?'success':'error'); }catch(e){}
      });
    }
  }
};

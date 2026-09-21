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
    if (typeof BrowserConnection === 'undefined') return;
    BrowserConnection.apply(cfg);   // selector + shared row + per-browser block (Chrome/Firefox)
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
      if (typeof BrowserConnection !== 'undefined') BrowserConnection.applyLaunch(cmd);
    } catch{}
  },

  loadCDPConfig() {
    if (App.bridge?.get_cdp_config) App.bridge.get_cdp_config((res)=> this._onCDPConfig(res));
    if (App.bridge?.get_chrome_launch_command) App.bridge.get_chrome_launch_command((res)=> this._onLaunchCmd(res));
  },

  updateChromeCmdPreview() {
    if (typeof BrowserConnection === 'undefined') return;
    BrowserConnection.updatePreview();          // the selected browser's own command
    BrowserConnection.updateToolbar();
    if (typeof CDPPanel !== 'undefined') CDPPanel.currentConfig = BrowserConnection.toolbarConfig();
  },

  _buildSettingsPayload() {
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
      watcher_generation_timeout_sec: genTo,
    };
    const interval = parseInt(getVal('setUrlIntervalMs'), 10); if (Number.isFinite(interval)) payload.url_reconcile_interval_ms = interval;  // empty field sends nothing (D-1)
    const hist = parseInt(getVal('setHistoryLimit'), 10); if (Number.isFinite(hist)) payload.job_history_limit = hist;  // Job History mirror: same rule, one Save click = one save_settings (I-61)
    return { payload, genTo };
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
    if (typeof BrowserConnection === 'undefined') return null;
    return BrowserConnection.payload();   // active browser + every per-browser block
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
    if (!payload) return;
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

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.SettingsPanel = SettingsPanel;

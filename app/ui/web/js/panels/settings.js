/* settings.js — including CDP host/port/user-data-dir user configurable */
'use strict';

const SettingsPanel = {
  cdpConfig: {host: '127.0.0.1', port: 9222, user_data_dir: 'C:\\arena-images-chrome', extra_args: ''},

  init() {
    document.getElementById('settingsSaveBtn')?.addEventListener('click', ()=>this.save());
    document.getElementById('settingsExportBtn')?.addEventListener('click', ()=>this.exportPreset());
    document.getElementById('settingsImportBtn')?.addEventListener('click', ()=>this.importPreset());

    // CDP config save button
    document.getElementById('cdpSaveBtn')?.addEventListener('click', ()=>this.saveCDP());
    document.getElementById('cdpTestBtn')?.addEventListener('click', ()=>this.testCDP());
    document.getElementById('cdpCopyCmdBtn')?.addEventListener('click', ()=>this.copyChromeCmd());

    // load CDP config on init
    setTimeout(()=>this.loadCDPConfig(), 1000);
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
  },

  saveCDP() {
    const getVal = (id) => document.getElementById(id)?.value;
    const host = (getVal('cdpHost')||'127.0.0.1').trim() || '127.0.0.1';
    let port = parseInt(getVal('cdpPort'))||9222;
    if (port < 1 || port > 65535) { LogConsole.log('⚠ Port must be 1-65535', 'warn'); return; }
    const user_data_dir = (getVal('cdpUserDataDir')||'C:\\arena-images-chrome').trim() || 'C:\\arena-images-chrome';
    const extra = (getVal('cdpExtraArgs')||'').trim();
    const payload = {host, port, user_data_dir, extra_args: extra};
    if (App.bridge && App.bridge.set_cdp_config) {
      App.bridge.set_cdp_config(JSON.stringify(payload), (res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`CDP config saved: ${host}:${port} dir=${user_data_dir} — restart Chrome with new command, then Diagnose`, 'success');
            this.cdpConfig = {host, port, user_data_dir, extra_args: extra};
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

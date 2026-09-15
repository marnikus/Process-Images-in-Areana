/* settings.js */
'use strict';

const SettingsPanel = {
  init() {
    document.getElementById('settingsSaveBtn')?.addEventListener('click', ()=>this.save());
    document.getElementById('settingsExportBtn')?.addEventListener('click', ()=>this.exportPreset());
    document.getElementById('settingsImportBtn')?.addEventListener('click', ()=>this.importPreset());
  },

  restore(state) {
    if (!state || !state.settings) return;
    const s = state.settings;
    const setVal = (id, v) => { const el=document.getElementById(id); if(el) el.value=v; };
    setVal('setTimeout', s.timeout_seconds || 120);
    setVal('setRetries', s.max_retries || 3);
    setVal('setNaming', s.naming_suffix || '_AI');
    setVal('setFileTypes', (s.supported_types||[]).join(','));
    setVal('setOverwrite', s.overwrite ? 'true' : 'false');
    setVal('setHighlightDur', s.highlight_duration || 3);
    setVal('setMaxConcurrent', s.max_concurrent || 1);
  },

  save() {
    const getVal = (id) => document.getElementById(id)?.value;
    const payload = {
      timeout_seconds: parseInt(getVal('setTimeout'))||120,
      max_retries: parseInt(getVal('setRetries'))||3,
      naming_suffix: getVal('setNaming')||'_AI',
      supported_types: (getVal('setFileTypes')||'.png,.jpg').split(',').map(x=>x.trim()).filter(Boolean),
      overwrite: getVal('setOverwrite')==='true',
      highlight_duration: parseInt(getVal('setHighlightDur'))||3,
      max_concurrent: parseInt(getVal('setMaxConcurrent'))||1,
    };
    if (App.bridge && App.bridge.save_settings) {
      App.bridge.save_settings(JSON.stringify(payload), (res)=>{
        try{ const r=JSON.parse(res); LogConsole.log(r.ok?'Settings saved':'Save failed: '+r.error, r.ok?'success':'error'); }catch(e){}
      });
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

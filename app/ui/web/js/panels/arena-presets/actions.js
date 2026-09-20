/* arena-presets/actions.js — C13 split: save/load/export/import actions, ≤200 LOC

   2026-10-02 bugfix: this module used to INJECT a second prompt-preset bar
   into #winPrompt and a second arena-preset bar into #winSettings whose
   ids collided with the static Arena Presets window (promptPresetSaveBtn,
   arenaPresetSaveBtn, arenaPresetExportBtn, arenaPresetImportBtn).
   document.getElementById() then bound whichever copy came first in DOM
   order, leaving the other window's buttons dead. All markup is now static
   in index.html with unique ids; this module only binds (once) and acts.

   Static ids:
     prompt bar (#winPrompt):  promptPresetName, promptPresetSaveBtn,
                               promptPresetSelect, promptPresetLoadBtn, promptPresetDeleteBtn
     Arena Presets window:     arenaPresetNameInput, arenaPresetSaveBtn, arenaPresetExportBtn,
                               arenaPresetImportBtn, arenaPresetFileInput, arenaPresetsList,
                               arenaPromptPresetNameInput, arenaPromptPresetSaveBtn, promptPresetsList
     Settings window:          presetNameInput, settingsExportBtn, settingsImportBtn (+ settingsSavePresetBtn) */
'use strict';

window.ArenaPresetsActions = {
  _store() { return window.ArenaPresetsStore; },
  _bridge() { return window.App && window.App.bridge; },

  _bind(id, ev, fn) {
    const el = document.getElementById(id);
    if (!el) return false;
    if (window.Boot) return window.Boot.bindOnce(el, ev, fn, `arena-presets:${id}`);
    el.addEventListener(ev, fn);
    return true;
  },

  _reply(res, okMsg, failPrefix, onOk) {
    try {
      const r = JSON.parse(res);
      if (r.ok) { LogConsole.log(okMsg, 'success'); if (onOk) onOk(r); }
      else LogConsole.log(`${failPrefix}: ${r.error || 'unknown error'}`, 'error');
    } catch { LogConsole.log(`${failPrefix}: bad reply`, 'error'); }
  },

  // ---- Settings window: "Save Settings Preset" (button created once) ----
  bindSettingsPresets() {
    const nameInput = document.getElementById('presetNameInput');
    const exportBtn = document.getElementById('settingsExportBtn');
    if (!nameInput || !exportBtn) return;
    let saveBtn = document.getElementById('settingsSavePresetBtn');
    if (!saveBtn) {
      saveBtn = document.createElement('button');
      saveBtn.id = 'settingsSavePresetBtn';
      saveBtn.className = 'btn-small btn-primary';
      saveBtn.textContent = 'Save Settings Preset';
      saveBtn.title = 'Save current settings as named preset';
      nameInput.parentNode.insertBefore(saveBtn, exportBtn);
    }
    this._bind('settingsSavePresetBtn', 'click', () => this._saveArenaNamed(nameInput));
  },

  // ---- Prompt window bar ----
  bindPromptPresets() {
    this._bind('promptPresetSaveBtn', 'click', () => this._savePrompt('promptPresetName'));
    this._bind('promptPresetLoadBtn', 'click', () => this._loadPrompt());
    this._bind('promptPresetDeleteBtn', 'click', () => this._deletePrompt());
    this._bind('promptPresetName', 'keydown', (e) => { if (e.key === 'Enter') this._savePrompt('promptPresetName'); });
    this._bind('arenaPromptPresetSaveBtn', 'click', () => this._savePrompt('arenaPromptPresetNameInput'));
  },

  _savePrompt(nameId) {
    const nameEl = document.getElementById(nameId);
    const name = nameEl ? nameEl.value.trim() : '';
    if (!name) { LogConsole.log('⚠ Enter prompt preset name', 'warn'); return; }
    const tmpl = document.getElementById('promptTextarea')?.value || '';
    if (!tmpl.trim()) { LogConsole.log('⚠ Prompt is empty — nothing to save', 'warn'); return; }
    this._store().savePromptPreset(name, tmpl, (res) =>
      this._reply(res, 'Prompt preset saved: ' + name, 'Save failed', () => { if (nameEl) nameEl.value = ''; this.loadPromptList(); }));
  },

  _selectedPrompt() {
    const sel = document.getElementById('promptPresetSelect');
    return sel ? sel.value : '';
  },

  applyPromptTemplate(tmpl) {
    const ta = document.getElementById('promptTextarea');
    if (!ta) return;
    ta.value = tmpl || '';
    if (typeof PromptEditor !== 'undefined') PromptEditor.updatePreview();
  },

  loadPromptByName(name) {
    if (!name) return;
    this._store().loadPromptPreset(name, (res) =>
      this._reply(res, 'Prompt preset loaded: ' + name, 'Load failed', (r) => this.applyPromptTemplate(r.template)));
  },

  deletePromptByName(name) {
    if (!name) return;
    this._store().deletePromptPreset(name, (res) =>
      this._reply(res, 'Prompt preset deleted: ' + name, 'Delete failed', () => this.loadPromptList()));
  },

  _loadPrompt() { this.loadPromptByName(this._selectedPrompt()); },
  _deletePrompt() { this.deletePromptByName(this._selectedPrompt()); },

  loadPromptList() {
    this._store().listPromptPresets((res) => {
      try { if (typeof res === 'string') window.ArenaPresetsRender.renderPromptPresets(res); } catch {}
    });
  },

  // ---- Arena Presets window (static markup) ----
  bindArenaPresets() {
    const nameInput = document.getElementById('arenaPresetNameInput');
    this._bind('arenaPresetSaveBtn', 'click', () => this._saveArenaNamed(nameInput));
    this._bind('arenaPresetNameInput', 'keydown', (e) => { if (e.key === 'Enter') this._saveArenaNamed(nameInput); });
    this._bind('arenaPresetExportBtn', 'click', () => this._exportArena(nameInput));
    const importFile = document.getElementById('arenaPresetFileInput');
    if (importFile) {
      this._bind('arenaPresetImportBtn', 'click', () => importFile.click());
      this._bind('arenaPresetFileInput', 'change', (e) => this._importArena(e));
    }
  },

  _saveArenaNamed(nameInput) {
    const name = (nameInput ? nameInput.value : '').trim();
    if (!name) { LogConsole.log('⚠ Enter arena preset name', 'warn'); return; }
    this._store().saveArenaPreset(name, (res) =>
      this._reply(res, 'Arena preset saved: ' + name, 'Save failed', () => { if (nameInput) nameInput.value = ''; }));
  },

  _exportArena(nameInput) {
    const state = window.App && window.App.state;
    if (!state) { LogConsole.log('⚠ Nothing to export yet', 'warn'); return; }
    const blob = new Blob([JSON.stringify(state, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `arena_preset_${(nameInput?.value || 'export')}.json`;
    a.click();
    URL.revokeObjectURL(url);
    LogConsole.log('Arena preset exported', 'success');
  },

  _applyPromptFromData(data) {
    if (!data.prompt) return;
    const tmpl = data.prompt.template || data.prompt.user_prompt || '';
    if (tmpl) this.applyPromptTemplate(tmpl);
  },

  _handleImportData(data, fileName) {
    const name = data.name || fileName.replace('.json','');
    this._applyPromptFromData(data);
    this._store().saveArenaPreset(name, () => {
      LogConsole.log('Imported arena preset: ' + name, 'success');
      const b = this._bridge();
      if (b && b.load_arena_preset) b.load_arena_preset(name, ()=>{});
    });
  },

  _importArena(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result);
        this._handleImportData(data, file.name);
      } catch (err) {
        LogConsole.log('Import failed: ' + err, 'error');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  },
};

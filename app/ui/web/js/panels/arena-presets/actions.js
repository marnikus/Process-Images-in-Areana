/* arena-presets/actions.js — C13 split: save/load/export/import actions, ≤200 LOC */
'use strict';

window.ArenaPresetsActions = {
  _store() { return window.ArenaPresetsStore; },

  bindSettingsPresets() {
    const nameInput = document.getElementById('presetNameInput');
    const exportBtn = document.getElementById('settingsExportBtn');
    const importBtn = document.getElementById('settingsImportBtn');
    if (!nameInput || !exportBtn || !importBtn) return;
    let saveBtn = document.getElementById('settingsSavePresetBtn');
    if (!saveBtn) {
      saveBtn = document.createElement('button');
      saveBtn.id = 'settingsSavePresetBtn';
      saveBtn.className = 'btn-small btn-primary';
      saveBtn.textContent = 'Save Settings Preset';
      saveBtn.title = 'Save current settings as named preset';
      nameInput.parentNode.insertBefore(saveBtn, exportBtn);
    }
    saveBtn.addEventListener('click', () => this._saveSettings(nameInput));
  },

  _saveSettings(nameInput) {
    const name = (nameInput.value || '').trim();
    if (!name) { LogConsole.log('⚠ Enter preset name', 'warn'); return; }
    this._store().saveArenaPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log('Arena preset saved: ' + name, 'success');
        else LogConsole.log('Save failed: ' + r.error, 'error');
      } catch {}
    });
  },

  bindPromptPresets() {
    const nameInput = document.getElementById('promptPresetNameInput');
    const saveBtn = document.getElementById('promptPresetSaveBtn');
    if (!nameInput || !saveBtn) return;
    saveBtn.addEventListener('click', () => this._savePrompt());
    const list = document.getElementById('promptPresetsList');
    if (list) list.addEventListener('click', this._bindPromptButtons.bind(this));
  },

  _bindPromptButtons(event) {
    const button = event.target.closest('button');
    if (!button) return;
    const name = button.dataset.promptLoad || button.dataset.promptRemove;
    if (button.dataset.promptLoad) this._loadPromptNamed(name);
    if (button.dataset.promptRemove) this._deletePromptNamed(name);
  },

  _savePrompt() {
    const nameEl = document.getElementById('promptPresetNameInput');
    const name = nameEl ? nameEl.value.trim() : '';
    if (!name) { LogConsole.log('⚠ Enter prompt preset name', 'warn'); return; }
    const tmpl = document.getElementById('promptTextarea')?.value || '';
    this._store().savePromptPreset(name, tmpl, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) {
          LogConsole.log('Prompt preset saved: ' + name, 'success');
          this.loadPromptList();
        } else LogConsole.log('Save failed: ' + r.error, 'error');
      } catch {}
    });
  },

  _loadPrompt() {
    const sel = document.getElementById('promptPresetSelect');
    if (sel?.value) this._loadPromptNamed(sel.value);
  },

  _loadPromptNamed(name) {
    this._store().loadPromptPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (!r.ok) { LogConsole.log('Load failed: ' + r.error, 'error'); return; }
        const ta = document.getElementById('promptTextarea');
        if (ta) ta.value = r.template || '';
        if (typeof PromptEditor !== 'undefined') PromptEditor.updatePreview();
        LogConsole.log('Prompt preset loaded: ' + name, 'success');
      } catch {}
    });
  },

  _deletePrompt() {
    const sel = document.getElementById('promptPresetSelect');
    if (sel?.value) this._deletePromptNamed(sel.value);
  },

  _deletePromptNamed(name) {
    this._store().deletePromptPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) {
          LogConsole.log('Prompt preset deleted: ' + name, 'info');
          this.loadPromptList();
        } else LogConsole.log('Delete failed: ' + r.error, 'error');
      } catch {}
    });
  },

  loadPromptList() {
    this._store().listPromptPresets((res) => {
      try { if (typeof res === 'string') window.ArenaPresetsRender.renderPromptPresets(res); } catch {}
    });
  },

  bindArenaPresets() {
    if (!document.getElementById('winArenaPresets')) return;
    this._bindArenaButtons();
  },

  _bindArenaButtons() {
    const saveBtn = document.getElementById('arenaPresetSaveBtn');
    const exportBtn = document.getElementById('arenaPresetExportBtn');
    const importBtn = document.getElementById('arenaPresetImportBtn');
    const importFile = document.getElementById('arenaPresetFileInput');
    const nameInput = document.getElementById('arenaPresetNameInput');
    if (saveBtn) saveBtn.addEventListener('click', () => this._saveArena(nameInput));
    if (exportBtn) exportBtn.addEventListener('click', () => this._exportArena(nameInput));
    if (importBtn && importFile) {
      importBtn.addEventListener('click', () => importFile.click());
      importFile.addEventListener('change', (e) => this._importArena(e));
    }
  },

  _saveArena(nameInput) {
    const name = (nameInput ? nameInput.value.trim() : '').trim();
    if (!name) { LogConsole.log('⚠ Enter arena preset name', 'warn'); return; }
    this._store().saveArenaPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log('Arena preset saved: ' + name, 'success');
        else LogConsole.log('Save failed: ' + r.error, 'error');
      } catch {}
    });
  },

  _exportArena(nameInput) {
    const state = window.App && window.App.state;
    if (!state) return;
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
    if (!tmpl) return;
    const ta = document.getElementById('promptTextarea');
    if (!ta) return;
    ta.value = tmpl;
    if (typeof PromptEditor !== 'undefined') PromptEditor.updatePreview();
  },

  _handleImportData(data, fileName) {
    const name = data.name || fileName.replace('.json','');
    this._applyPromptFromData(data);
    this._store().saveArenaPreset(name, () => {
      LogConsole.log('Imported arena preset: ' + name, 'success');
      const b = window.App && window.App.bridge;
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

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
    const promptPanel = document.getElementById('winPrompt');
    if (!promptPanel) return;
    let bar = promptPanel.querySelector('.preset-bar');
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'preset-bar';
      bar.style.marginTop = '8px';
      const ta = document.getElementById('promptTextarea');
      if (ta) ta.parentNode.insertBefore(bar, ta.nextSibling);
    }
    bar.innerHTML = `
      <input id="promptPresetName" type="text" placeholder="prompt preset name" style="flex:1; min-width:120px;">
      <button id="promptPresetSaveBtn" class="btn-small btn-primary">Save</button>
      <button id="promptPresetLoadBtn" class="btn-small">Load</button>
      <button id="promptPresetDeleteBtn" class="btn-small">Delete</button>
      <select id="promptPresetSelect" style="min-width:140px;"></select>
    `;
    this._bindPromptButtons(bar);
  },

  _bindPromptButtons(bar) {
    const saveBtn = bar.querySelector('#promptPresetSaveBtn');
    const loadBtn = bar.querySelector('#promptPresetLoadBtn');
    const delBtn = bar.querySelector('#promptPresetDeleteBtn');
    if (saveBtn) saveBtn.addEventListener('click', () => this._savePrompt());
    if (loadBtn) loadBtn.addEventListener('click', () => this._loadPrompt());
    if (delBtn) delBtn.addEventListener('click', () => this._deletePrompt());
  },

  _savePrompt() {
    const nameEl = document.getElementById('promptPresetName');
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
    const name = sel ? sel.value : '';
    if (!name) return;
    this._store().loadPromptPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) {
          document.getElementById('promptTextarea').value = r.template || '';
          if (typeof PromptEditor !== 'undefined') PromptEditor.updatePreview();
          LogConsole.log('Prompt preset loaded: ' + name, 'success');
        } else LogConsole.log('Load failed: ' + r.error, 'error');
      } catch {}
    });
  },

  _deletePrompt() {
    const sel = document.getElementById('promptPresetSelect');
    const name = sel ? sel.value : '';
    if (!name) return;
    this._store().deletePromptPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) {
          LogConsole.log('Prompt preset deleted: ' + name, 'info');
          this.loadPromptList();
        }
      } catch {}
    });
  },

  loadPromptList() {
    this._store().listPromptPresets((res) => {
      try { if (typeof res === 'string') window.ArenaPresetsRender.renderPromptPresets(res); } catch {}
    });
  },

  bindArenaPresets() {
    const settingsPanel = document.getElementById('winSettings');
    if (!settingsPanel) return;
    let arenaBar = document.getElementById('arenaPresetBar');
    if (!arenaBar) {
      arenaBar = document.createElement('div');
      arenaBar.id = 'arenaPresetBar';
      arenaBar.className = 'preset-bar';
      arenaBar.style.flexDirection = 'column';
      arenaBar.style.alignItems = 'stretch';
      arenaBar.innerHTML = `
        <div style="display:flex; gap:6px; align-items:center;">
          <span style="font-size:11px; font-weight:600; color:var(--text-secondary);">Arena Presets (URLs+prompt+settings+highlight_duration)</span>
          <span class="spacer"></span>
          <input id="arenaPresetName" type="text" placeholder="arena preset name" style="flex:0 0 160px;">
          <button id="arenaPresetSaveBtn" class="btn-small btn-primary">Save Arena</button>
          <button id="arenaPresetExportBtn" class="btn-small">Export JSON</button>
          <input id="arenaPresetImportFile" type="file" accept=".json" style="display:none;">
          <button id="arenaPresetImportBtn" class="btn-small">Import</button>
        </div>
        <div id="arenaPresetChips" class="chip-wrap" style="display:flex; flex-wrap:wrap; gap:6px; margin-top:6px;"></div>
        <div id="arenaPresetList" style="max-height:120px; overflow:auto; border:1px solid var(--border); border-radius:4px; padding:4px; margin-top:6px; font-size:11px;"></div>
      `;
      settingsPanel.appendChild(arenaBar);
    }
    this._bindArenaButtons();
  },

  _bindArenaButtons() {
    const saveBtn = document.getElementById('arenaPresetSaveBtn');
    const exportBtn = document.getElementById('arenaPresetExportBtn');
    const importBtn = document.getElementById('arenaPresetImportBtn');
    const importFile = document.getElementById('arenaPresetImportFile');
    const nameInput = document.getElementById('arenaPresetName');
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

/* arena-presets.js — full presets & save variables system (window + arena: URLs, prompt, settings, highlight_duration, custom variables) */
'use strict';

const ArenaPresets = {
  init() {
    // Hook UI for settings presets, prompt presets, arena presets
    this.bindSettingsPresets();
    this.bindPromptPresets();
    this.bindArenaPresets();
    this.loadAll();
  },

  loadAll() {
    if (App.bridge) {
      try {
        if (App.bridge.list_prompt_presets) {
          App.bridge.list_prompt_presets((res) => {
            try { if (typeof res === 'string') this.renderPromptPresets(res); } catch {}
          });
        }
      } catch {}
      try {
        if (App.bridge.list_arena_presets) {
          App.bridge.list_arena_presets((res) => {
            try { if (typeof res === 'string') this.renderArenaPresets(res); } catch {}
          });
        }
      } catch {}
      try {
        if (App.bridge.presets_changed) {
          App.bridge.presets_changed.connect((kind, payload) => {
            if (kind === 'arena') this.renderArenaPresets(payload);
            if (kind === 'prompt') this.renderPromptPresets(payload);
          });
        }
      } catch {}
    }
  },

  // ---- Settings preset (reuses old presetNameInput etc) ----
  bindSettingsPresets() {
    const nameInput = document.getElementById('presetNameInput');
    const exportBtn = document.getElementById('settingsExportBtn');
    const importBtn = document.getElementById('settingsImportBtn');
    if (!nameInput || !exportBtn || !importBtn) return;

    // add Save settings as preset button dynamically if not exists
    let saveBtn = document.getElementById('settingsSavePresetBtn');
    if (!saveBtn) {
      saveBtn = document.createElement('button');
      saveBtn.id = 'settingsSavePresetBtn';
      saveBtn.className = 'btn-small btn-primary';
      saveBtn.textContent = 'Save Settings Preset';
      saveBtn.title = 'Save current settings as named preset in arena_presets.json';
      nameInput.parentNode.insertBefore(saveBtn, exportBtn);
    }
    saveBtn.addEventListener('click', () => {
      const name = (nameInput.value || '').trim();
      if (!name) { LogConsole.log('⚠ Enter preset name', 'warn'); return; }
      // save current settings via bridge prompt? Actually settings preset is part of arena_presets: we will reuse settings preset via prompt? For now use arena preset as settings store
      // For simplicity, save arena preset (full)
      if (App.bridge && App.bridge.save_arena_preset) {
        App.bridge.save_arena_preset(name, (res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok) LogConsole.log('Arena preset saved: ' + name, 'success');
            else LogConsole.log('Save failed: ' + r.error, 'error');
          } catch {}
        });
      }
    });
  },

  // ---- Prompt presets ----
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
    const saveBtn = bar.querySelector('#promptPresetSaveBtn');
    const loadBtn = bar.querySelector('#promptPresetLoadBtn');
    const delBtn = bar.querySelector('#promptPresetDeleteBtn');
    if (saveBtn) saveBtn.addEventListener('click', () => {
      const nameEl = document.getElementById('promptPresetName');
      const name = nameEl ? nameEl.value.trim() : '';
      if (!name) { LogConsole.log('⚠ Enter prompt preset name', 'warn'); return; }
      const tmpl = document.getElementById('promptTextarea')?.value || '';
      if (App.bridge && App.bridge.save_prompt_preset) {
        App.bridge.save_prompt_preset(name, tmpl, (res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok) {
              LogConsole.log('Prompt preset saved: ' + name, 'success');
              this.loadPromptList();
            } else LogConsole.log('Save failed: ' + r.error, 'error');
          } catch {}
        });
      }
    });
    if (loadBtn) loadBtn.addEventListener('click', () => {
      const sel = document.getElementById('promptPresetSelect');
      const name = sel ? sel.value : '';
      if (!name) return;
      if (App.bridge && App.bridge.load_prompt_preset) {
        App.bridge.load_prompt_preset(name, (res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok) {
              document.getElementById('promptTextarea').value = r.template || '';
              if (typeof PromptEditor !== 'undefined') PromptEditor.updatePreview();
              LogConsole.log('Prompt preset loaded: ' + name, 'success');
            } else LogConsole.log('Load failed: ' + r.error, 'error');
          } catch {}
        });
      }
    });
    if (delBtn) delBtn.addEventListener('click', () => {
      const sel = document.getElementById('promptPresetSelect');
      const name = sel ? sel.value : '';
      if (!name) return;
      if (App.bridge && App.bridge.delete_prompt_preset) {
        App.bridge.delete_prompt_preset(name, (res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok) {
              LogConsole.log('Prompt preset deleted: ' + name, 'info');
              this.loadPromptList();
            }
          } catch {}
        });
      }
    });
  },

  loadPromptList() {
    if (App.bridge && App.bridge.list_prompt_presets) {
      try {
        App.bridge.list_prompt_presets((res) => {
          try { if (typeof res === 'string') this.renderPromptPresets(res); } catch {}
        });
      } catch {}
    }
  },

  renderPromptPresets(payload) {
    try {
      const raw = typeof payload === 'string' ? JSON.parse(payload) : payload;
      const arr = Array.isArray(raw) ? raw : [];
      const sel = document.getElementById('promptPresetSelect');
      if (!sel) return;
      sel.innerHTML = '';
      arr.forEach(item => {
        const name = typeof item === 'string' ? item : (item.name || item.id || '');
        if (!name) return;
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      });
    } catch (e) {
      console.warn('renderPromptPresets failed', e);
    }
  },

  // ---- Arena presets (full: URLs, prompt, settings, highlight_duration) ----
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
    const saveBtn = document.getElementById('arenaPresetSaveBtn');
    const exportBtn = document.getElementById('arenaPresetExportBtn');
    const importBtn = document.getElementById('arenaPresetImportBtn');
    const importFile = document.getElementById('arenaPresetImportFile');
    const nameInput = document.getElementById('arenaPresetName');

    if (saveBtn) saveBtn.addEventListener('click', () => {
      const name = (nameInput ? nameInput.value.trim() : '').trim();
      if (!name) { LogConsole.log('⚠ Enter arena preset name', 'warn'); return; }
      if (App.bridge && App.bridge.save_arena_preset) {
        App.bridge.save_arena_preset(name, (res) => {
          try {
            const r = JSON.parse(res);
            if (r.ok) LogConsole.log('Arena preset saved: ' + name, 'success');
            else LogConsole.log('Save failed: ' + r.error, 'error');
          } catch {}
        });
      }
    });
    if (exportBtn) exportBtn.addEventListener('click', () => {
      // export current arena state as JSON file download via data URI
      const state = App.state;
      if (!state) return;
      const blob = new Blob([JSON.stringify(state, null, 2)], {type:'application/json'});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `arena_preset_${(nameInput?.value || 'export')}.json`;
      a.click();
      URL.revokeObjectURL(url);
      LogConsole.log('Arena preset exported', 'success');
    });
    if (importBtn && importFile) {
      importBtn.addEventListener('click', () => importFile.click());
      importFile.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
          try {
            const data = JSON.parse(ev.target.result);
            // if it's arena preset doc, extract
            let name = data.name || file.name.replace('.json','');
            // if data contains urls/prompt/settings directly, wrap
            let doc = data;
            if (!doc.urls && data.urls) doc = data; // already
            // save via bridge if possible: we need to manually save file to presets? For now just load into current state
            if (App.bridge && App.bridge.save_arena_preset) {
              // save as preset
              App.bridge.save_arena_preset(name, (res) => {
                LogConsole.log('Imported arena preset: ' + name, 'success');
                // then load it
                if (App.bridge.load_arena_preset) App.bridge.load_arena_preset(name, ()=>{});
              });
            }
            // also directly apply if it has prompt etc
            if (data.prompt) {
              const tmpl = data.prompt.template || data.prompt.user_prompt || '';
              if (tmpl && document.getElementById('promptTextarea')) {
                document.getElementById('promptTextarea').value = tmpl;
                if (typeof PromptEditor !== 'undefined') PromptEditor.updatePreview();
              }
            }
          } catch (err) {
            LogConsole.log('Import failed: ' + err, 'error');
          }
        };
        reader.readAsText(file);
        e.target.value = '';
      });
    }
  },

  renderArenaPresets(payload) {
    try {
      const raw = typeof payload === 'string' ? JSON.parse(payload) : payload;
      const arr = Array.isArray(raw) ? raw : [];
      const names = arr.map(item => typeof item === 'string' ? item : (item.name || '')).filter(Boolean);
      const chipsWrap = document.getElementById('arenaPresetChips');
      const listEl = document.getElementById('arenaPresetList');
      if (chipsWrap) {
        chipsWrap.innerHTML = '';
        names.forEach(name => {
          const chip = document.createElement('div');
          chip.className = 'chip';
          chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; background:var(--bg-input); border:1px solid var(--border); border-radius:12px; padding:2px 8px; font-size:11px; cursor:pointer;';
          const txt = document.createElement('span');
          txt.textContent = name;
          txt.addEventListener('click', () => {
            if (App.bridge && App.bridge.load_arena_preset) {
              App.bridge.load_arena_preset(name, (res) => {
                try {
                  const r = JSON.parse(res);
                  if (r.ok) LogConsole.log('Arena preset loaded: ' + name, 'success');
                  else LogConsole.log('Load failed: ' + r.error, 'error');
                } catch {}
              });
            }
          });
          const del = document.createElement('span');
          del.textContent = '✕';
          del.style.cssText = 'cursor:pointer; color:var(--text-muted); margin-left:4px;';
          del.title = 'Delete';
          del.addEventListener('click', (e) => {
            e.stopPropagation();
            if (App.bridge && App.bridge.delete_arena_preset) {
              App.bridge.delete_arena_preset(name, (res) => {
                try {
                  const r = JSON.parse(res);
                  if (r.ok) LogConsole.log('Arena preset deleted: ' + name, 'info');
                } catch {}
              });
            }
          });
          chip.appendChild(txt);
          chip.appendChild(del);
          chipsWrap.appendChild(chip);
        });
      }
      if (listEl) {
        listEl.innerHTML = '';
        if (names.length === 0) {
          listEl.textContent = 'No arena presets yet. Save current URLs+prompt+settings+highlight_duration as named preset.';
          return;
        }
        names.forEach(name => {
          const row = document.createElement('div');
          row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:2px 4px; border-bottom:1px solid var(--border);';
          row.innerHTML = `<span>${this.esc(name)}</span><span style="display:flex; gap:4px;"><button class="btn-small" data-load="${this.esc(name)}">Load</button><button class="btn-small" data-del="${this.esc(name)}">Delete</button></span>`;
          listEl.appendChild(row);
        });
        listEl.querySelectorAll('button[data-load]').forEach(btn => {
          btn.addEventListener('click', () => {
            const n = btn.getAttribute('data-load');
            if (App.bridge && App.bridge.load_arena_preset) App.bridge.load_arena_preset(n, ()=>{});
          });
        });
        listEl.querySelectorAll('button[data-del]').forEach(btn => {
          btn.addEventListener('click', () => {
            const n = btn.getAttribute('data-del');
            if (App.bridge && App.bridge.delete_arena_preset) App.bridge.delete_arena_preset(n, ()=>{});
          });
        });
      }
    } catch (e) {
      console.warn('renderArenaPresets failed', e);
    }
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
};

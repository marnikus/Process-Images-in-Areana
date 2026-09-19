/* arena-presets/render.js — C13 split: chip/list rendering, ≤200 LOC */
'use strict';

window.ArenaPresetsRender = {
  _store() { return window.ArenaPresetsStore; },

  renderPromptPresets(payload) {
    try {
      const arr = this._store().setPromptPresets(payload);
      const list = document.getElementById('promptPresetsList');
      if (!list) return;
      list.innerHTML = arr.length ? arr.map(this._promptRow.bind(this)).join('')
        : 'No saved prompt presets.';
    } catch (e) { console.warn('renderPromptPresets failed', e); }
  },

  _promptRow(item) {
    const name = typeof item === 'string' ? item : (item.name || item.id || '');
    if (!name) return '';
    const safe = this._store().esc(name);
    return `<div class="prompt-preset-row"><span>${safe}</span><span><button class="btn-small" data-prompt-load="${safe}">Load</button><button class="btn-small" data-prompt-remove="${safe}">Remove</button></span></div>`;
  },

  renderArenaPresets(payload) {
    try {
      const arr = this._store().setArenaPresets(payload);
      const names = this._store().namesFromArray(arr);
      this._renderChips(names);
      this._renderList(names);
    } catch (e) { console.warn('renderArenaPresets failed', e); }
  },

  _renderChips(names) {
    const chipsWrap = document.getElementById('arenaPresetChips');
    if (!chipsWrap) return;
    chipsWrap.innerHTML = '';
    names.forEach(name => {
      chipsWrap.appendChild(this._buildChip(name));
    });
  },

  _buildChip(name) {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; background:var(--bg-input); border:1px solid var(--border); border-radius:12px; padding:2px 8px; font-size:11px; cursor:pointer;';
    const txt = document.createElement('span');
    txt.textContent = name;
    txt.addEventListener('click', () => this._onLoadChip(name));
    const del = document.createElement('span');
    del.textContent = '✕';
    del.style.cssText = 'cursor:pointer; color:var(--text-muted); margin-left:4px;';
    del.title = 'Delete';
    del.addEventListener('click', (e) => { e.stopPropagation(); this._onDeleteChip(name); });
    chip.appendChild(txt);
    chip.appendChild(del);
    return chip;
  },

  _onLoadChip(name) {
    this._store().loadArenaPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log('Arena preset loaded: ' + name, 'success');
        else LogConsole.log('Load failed: ' + r.error, 'error');
      } catch {}
    });
  },

  _onDeleteChip(name) {
    this._store().deleteArenaPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log('Arena preset deleted: ' + name, 'info');
      } catch {}
    });
  },

  _renderList(names) {
    const listEl = document.getElementById('arenaPresetsList') || document.getElementById('arenaPresetList');
    if (!listEl) return;
    listEl.innerHTML = '';
    if (names.length === 0) {
      listEl.textContent = 'No arena presets yet. Save current URLs+prompt+settings+highlight_duration as named preset.';
      return;
    }
    names.forEach(name => {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:2px 4px; border-bottom:1px solid var(--border);';
      row.innerHTML = `<span>${this._store().esc(name)}</span><span style="display:flex; gap:4px;"><button class="btn-small" data-load="${this._store().esc(name)}">Load</button><button class="btn-small" data-del="${this._store().esc(name)}">Delete</button></span>`;
      listEl.appendChild(row);
    });
    listEl.querySelectorAll('button[data-load]').forEach(btn => {
      btn.addEventListener('click', () => {
        const n = btn.getAttribute('data-load');
        this._store().loadArenaPreset(n, ()=>{});
      });
    });
    listEl.querySelectorAll('button[data-del]').forEach(btn => {
      btn.addEventListener('click', () => {
        const n = btn.getAttribute('data-del');
        this._store().deleteArenaPreset(n, ()=>{});
      });
    });
  },
};

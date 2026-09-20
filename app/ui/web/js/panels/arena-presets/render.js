/* arena-presets/render.js — C13 split: list rendering, ≤200 LOC

   Renders into the STATIC containers of index.html (2026-10-02 bugfix —
   no injected bars, no duplicate ids):
     promptPresetSelect  — <select> in the Prompt Editor bar
     promptPresetsList   — prompt preset rows in the Arena Presets window
     arenaPresetsList    — arena preset rows (Load / Delete) + arenaPresetsCount badge */
'use strict';

window.ArenaPresetsRender = {
  _store() { return window.ArenaPresetsStore; },
  _actions() { return window.ArenaPresetsActions; },

  _names(arr) {
    return arr.map(item => typeof item === 'string' ? item : (item.name || item.id || '')).filter(Boolean);
  },

  renderPromptPresets(payload) {
    try {
      const names = this._names(this._store().setPromptPresets(payload));
      this._renderPromptSelect(names);
      this._renderRows('promptPresetsList', names, {
        empty: 'No prompt presets yet — type a name next to the Prompt Editor and press Save.',
        onLoad: (n) => this._actions().loadPromptByName(n),
        onDelete: (n) => this._actions().deletePromptByName(n),
      });
    } catch (e) { console.warn('renderPromptPresets failed', e); }
  },

  _renderPromptSelect(names) {
    const sel = document.getElementById('promptPresetSelect');
    if (!sel) return;
    const keep = sel.value;
    sel.innerHTML = '';
    names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
    if (keep && names.includes(keep)) sel.value = keep;
  },

  renderArenaPresets(payload) {
    try {
      const names = this._names(this._store().setArenaPresets(payload));
      const count = document.getElementById('arenaPresetsCount');
      if (count) count.textContent = `${names.length} preset${names.length === 1 ? '' : 's'}`;
      this._renderRows('arenaPresetsList', names, {
        empty: 'No arena presets yet. Save current URLs+prompt+settings+highlight_duration as named preset.',
        onLoad: (n) => this._onLoadArena(n),
        onDelete: (n) => this._onDeleteArena(n),
      });
    } catch (e) { console.warn('renderArenaPresets failed', e); }
  },

  _onLoadArena(name) {
    this._store().loadArenaPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log('Arena preset loaded: ' + name, 'success');
        else LogConsole.log('Load failed: ' + r.error, 'error');
      } catch {}
    });
  },

  _onDeleteArena(name) {
    const run = () => this._store().deleteArenaPreset(name, (res) => {
      try {
        const r = JSON.parse(res);
        if (r.ok) LogConsole.log('Arena preset deleted: ' + name, 'info');
      } catch {}
    });
    if (window.Dialog?.confirm) window.Dialog.confirm('Delete arena preset', `Delete "${name}"?`, 'Delete', run);
    else run();
  },

  _button(label, onClick) {
    const btn = document.createElement('button');
    btn.className = 'btn-small';
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  },

  _row(name, handlers) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex; align-items:center; justify-content:space-between; padding:2px 4px; border-bottom:1px solid var(--border); font-size:11px;';
    const label = document.createElement('span');
    label.textContent = name;                       // textContent — no HTML injection from preset names
    const actions = document.createElement('span');
    actions.style.cssText = 'display:flex; gap:4px;';
    actions.appendChild(this._button('Load', () => handlers.onLoad(name)));
    actions.appendChild(this._button('Delete', () => handlers.onDelete(name)));
    row.appendChild(label);
    row.appendChild(actions);
    return row;
  },

  /** handlers: {empty, onLoad(name), onDelete(name)} */
  _renderRows(listId, names, handlers) {
    const listEl = document.getElementById(listId);
    if (!listEl) return;
    listEl.innerHTML = '';
    if (names.length === 0) { listEl.textContent = handlers.empty; return; }
    names.forEach(name => listEl.appendChild(this._row(name, handlers)));
  },
};

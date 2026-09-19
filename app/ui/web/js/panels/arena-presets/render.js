/* arena-presets/render.js — C13 split: chip/list rendering, ≤200 LOC */
'use strict';

window.ArenaPresetsRender = {
  _store() { return window.ArenaPresetsStore; },

  /* BUG 03.6: the prompt preset list lives in the static #promptPresetsList
     and is owned by the PromptPresets panel (per-row Restore/Remove). The
     injected <select id="promptPresetSelect"> is gone. */
  renderPromptPresets(payload) {
    try {
      this._store().setPromptPresets(payload);
      if (window.PromptPresets && PromptPresets.refresh) {
        PromptPresets.refresh();
      } else if (typeof LogConsole !== 'undefined') {
        LogConsole.log('⚠ Prompt preset update arrived but PromptPresets panel is not loaded', 'warn');
      }
    } catch (e) { console.warn('renderPromptPresets failed', e); }
  },

  renderArenaPresets(payload) {
    try {
      const arr = this._store().setArenaPresets(payload);
      const names = this._store().namesFromArray(arr);
      this._renderList(names);
    } catch (e) { console.warn('renderArenaPresets failed', e); }
  },

  _renderList(names) {
    /* Static #winArenaPresets markup — the injected #arenaPresetList is gone. */
    const listEl = document.getElementById('arenaPresetsList');
    const countEl = document.getElementById('arenaPresetsCount');
    if (countEl) countEl.textContent = `${names.length} preset${names.length === 1 ? '' : 's'}`;
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

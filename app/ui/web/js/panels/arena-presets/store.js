/* arena-presets/store.js — C13 split: state + bridge delegation, ≤200 LOC, CC≤10 */
'use strict';

window.ArenaPresetsStore = {
  _promptPresets: [],
  _arenaPresets: [],

  get promptPresets() { return this._promptPresets; },
  set promptPresets(v) { this._promptPresets = v; },
  get arenaPresets() { return this._arenaPresets; },
  set arenaPresets(v) { this._arenaPresets = v; },

  _parseArray(payload) {
    try {
      const raw = typeof payload === 'string' ? JSON.parse(payload) : payload;
      return Array.isArray(raw) ? raw : [];
    } catch { return []; }
  },

  setPromptPresets(payload) {
    this._promptPresets = this._parseArray(payload);
    return this._promptPresets;
  },

  setArenaPresets(payload) {
    const arr = this._parseArray(payload);
    this._arenaPresets = arr;
    return arr;
  },

  namesFromArray(arr) {
    return arr.map(item => typeof item === 'string' ? item : (item.name || '')).filter(Boolean);
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  // bridge wrappers
  listPromptPresets(cb) {
    const b = window.App && window.App.bridge;
    if (b && b.list_prompt_presets) { try { b.list_prompt_presets(cb); } catch {} }
  },
  listArenaPresets(cb) {
    const b = window.App && window.App.bridge;
    if (b && b.list_arena_presets) { try { b.list_arena_presets(cb); } catch {} }
  },
  savePromptPreset(name, tmpl, cb) {
    const b = window.App && window.App.bridge;
    if (b && b.save_prompt_preset) b.save_prompt_preset(name, tmpl, cb);
  },
  loadPromptPreset(name, cb) {
    const b = window.App && window.App.bridge;
    if (b && b.load_prompt_preset) b.load_prompt_preset(name, cb);
  },
  deletePromptPreset(name, cb) {
    const b = window.App && window.App.bridge;
    if (b && b.delete_prompt_preset) b.delete_prompt_preset(name, cb);
  },
  saveArenaPreset(name, cb) {
    const b = window.App && window.App.bridge;
    if (b && b.save_arena_preset) b.save_arena_preset(name, cb);
  },
  loadArenaPreset(name, cb) {
    const b = window.App && window.App.bridge;
    if (b && b.load_arena_preset) b.load_arena_preset(name, cb);
  },
  deleteArenaPreset(name, cb) {
    const b = window.App && window.App.bridge;
    if (b && b.delete_arena_preset) b.delete_arena_preset(name, cb);
  },
};

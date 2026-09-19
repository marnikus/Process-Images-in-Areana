/* arena-presets.js — facade C13 split into store/render/actions, RULE18 file 150-300 */
'use strict';

const ArenaPresets = {
  _store: null,
  _render: null,
  _actions: null,

  init() {
    this._store = window.ArenaPresetsStore;
    this._render = window.ArenaPresetsRender;
    this._actions = window.ArenaPresetsActions;
    this._actions.bindSettingsPresets();
    this._actions.bindArenaPresets();
    // BUG 03.6: prompt presets are bound by the PromptPresets panel (static
    // #winArenaPresets markup) — no injected bar, no duplicate ids.
    this.loadAll();
  },

  _loadPromptPresets() {
    try {
      if (window.App.bridge.list_prompt_presets) {
        window.App.bridge.list_prompt_presets((res) => {
          try { if (typeof res === 'string') this.renderPromptPresets(res); } catch {}
        });
      }
    } catch {}
  },

  _loadArenaPresets() {
    try {
      if (window.App.bridge.list_arena_presets) {
        window.App.bridge.list_arena_presets((res) => {
          try { if (typeof res === 'string') this.renderArenaPresets(res); } catch {}
        });
      }
    } catch {}
  },

  _bindPresetsChanged() {
    try {
      if (window.App.bridge.presets_changed) {
        window.App.bridge.presets_changed.connect((kind, payload) => {
          if (kind === 'arena') this.renderArenaPresets(payload);
          if (kind === 'prompt') this.renderPromptPresets(payload);
        });
      }
    } catch {}
  },

  loadAll() {
    if (!window.App?.bridge) return;
    this._loadPromptPresets();
    this._loadArenaPresets();
    this._bindPresetsChanged();
  },

  bindSettingsPresets() { this._actions.bindSettingsPresets(); },
  bindArenaPresets() { this._actions.bindArenaPresets(); },

  renderPromptPresets(payload) { this._render.renderPromptPresets(payload); },
  renderArenaPresets(payload) { this._render.renderArenaPresets(payload); },

  esc(s) { return this._store.esc(s); },
};

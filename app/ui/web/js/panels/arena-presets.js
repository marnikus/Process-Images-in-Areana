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
    this._actions.bindPromptPresets();
    this._actions.bindArenaPresets();
    this.loadAll();
  },

  loadAll() {
    if (window.App && window.App.bridge) {
      try {
        if (window.App.bridge.list_prompt_presets) {
          window.App.bridge.list_prompt_presets((res) => {
            try { if (typeof res === 'string') this.renderPromptPresets(res); } catch {}
          });
        }
      } catch {}
      try {
        if (window.App.bridge.list_arena_presets) {
          window.App.bridge.list_arena_presets((res) => {
            try { if (typeof res === 'string') this.renderArenaPresets(res); } catch {}
          });
        }
      } catch {}
      try {
        if (window.App.bridge.presets_changed) {
          window.App.bridge.presets_changed.connect((kind, payload) => {
            if (kind === 'arena') this.renderArenaPresets(payload);
            if (kind === 'prompt') this.renderPromptPresets(payload);
          });
        }
      } catch {}
    }
  },

  bindSettingsPresets() { this._actions.bindSettingsPresets(); },
  bindPromptPresets() { this._actions.bindPromptPresets(); },
  bindArenaPresets() { this._actions.bindArenaPresets(); },
  loadPromptList() { this._actions.loadPromptList(); },

  renderPromptPresets(payload) { this._render.renderPromptPresets(payload); },
  renderArenaPresets(payload) { this._render.renderArenaPresets(payload); },

  esc(s) { return this._store.esc(s); },
};

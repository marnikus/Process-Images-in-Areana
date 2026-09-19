/* arena-history.js — global undo/redo timeline, RULE18 file 150-300, CC≤10 via dispatch */
'use strict';

const ArenaHistory = {
  globalHistory: [],
  globalHistoryIndex: -1,
  UNDO_KINDS: ['grid', 'urls', 'folder', 'queue', 'prompt', 'settings', 'window_states', 'arena'],

  _copy(value) {
    try { return JSON.parse(JSON.stringify(value)); } catch (e) { return value; }
  },

  _same(a, b) {
    try { return JSON.stringify(a) === JSON.stringify(b); } catch (e) { return a === b; }
  },

  loadGlobalHistory(state) {
    state = state || {};
    let history = Array.isArray(state.undo_history) ? state.undo_history : [];
    if (!history.length && state.history && Array.isArray(state.history)) history = state.history;
    this.globalHistory = history.filter(e => e && this.UNDO_KINDS.includes(e.kind))
      .map(e => ({ kind: e.kind, value: this._copy(e.value) }));
    const idx = Number.isInteger(state.undo_history_index) ? state.undo_history_index
      : (Number.isInteger(state.index) ? state.index : this.globalHistory.length - 1);
    this.globalHistoryIndex = Math.max(-1, Math.min(idx, this.globalHistory.length - 1));
    this._updateUndoButtons();
  },

  recordGlobal(kind, value, options) {
    options = options || {};
    const entry = { kind, value: this._copy(value) };
    const current = this.globalHistory[this.globalHistoryIndex];
    if (current && this._same(current, entry)) return;
    if (this.globalHistoryIndex < this.globalHistory.length - 1) {
      this.globalHistory = this.globalHistory.slice(0, this.globalHistoryIndex + 1);
    }
    this.globalHistory.push(entry);
    this.globalHistoryIndex = this.globalHistory.length - 1;
    if (this.globalHistory.length > 100) {
      this.globalHistory.splice(0, this.globalHistory.length - 100);
      this.globalHistoryIndex = this.globalHistory.length - 1;
    }
    this._updateUndoButtons();
    if (!options.localOnly && App.bridge && App.bridge.push_global_history) {
      try { App.bridge.push_global_history(kind, JSON.stringify(value)); } catch (e) { console.warn('push_global_history failed', e); }
    }
  },

  _isEmptyResult(result) {
    return result.empty || result.value === null || result.value === undefined;
  },

  _handleEmptyGrid() {
    try {
      if (typeof SashCore !== 'undefined' && SashCore.defaultTree) {
        SashGrid.root = SashCore.defaultTree();
        SashGrid.render();
        try { localStorage.setItem(SashGrid.STORAGE_KEY, SashCore.serialize(SashGrid.root)); } catch (e) {}
      }
    } catch (e) {}
    if (typeof LogConsole !== 'undefined') LogConsole.log('↩ Undo grid → default', 'info');
  },

  _parseResult(raw) {
    if (!raw || raw === 'null') return null;
    try {
      const result = JSON.parse(raw);
      if (!result || !result.kind) return null;
      return result;
    } catch (e) { return null; }
  },

  _applyEmptyResult(result) {
    const undone = result.undone || {};
    const undoneKind = undone.kind || result.kind;
    if (undoneKind === 'grid' && typeof SashGrid !== 'undefined') {
      this._handleEmptyGrid();
      this._updateUndoButtons();
      return true;
    }
    const emptyResult = { kind: undoneKind, value: result.value, index: -1, empty: true, undone: undone };
    this._applyGlobalKind(emptyResult);
    this._updateUndoButtons();
    return true;
  },

  _applyGlobalResult(raw) {
    const result = this._parseResult(raw);
    if (!result) return false;
    if (Number.isInteger(result.index)) this.globalHistoryIndex = result.index;
    if (result.index === -1 && this._isEmptyResult(result)) {
      return this._applyEmptyResult(result);
    }
    this._applyGlobalKind(result);
    this._updateUndoButtons();
    return true;
  },

  _handleGrid(result, isEmpty) {
    if (typeof SashGrid === 'undefined') return;
    if (isEmpty) {
      try {
        if (typeof SashCore !== 'undefined' && SashCore.defaultTree) {
          SashGrid.root = SashCore.defaultTree();
          SashGrid.render();
          try { localStorage.setItem(SashGrid.STORAGE_KEY, SashCore.serialize(SashGrid.root)); } catch (e) {}
        }
      } catch (e) {}
    } else {
      SashGrid._applySerialized(result.value, false);
    }
  },

  _clearWindowStates() {
    localStorage.setItem(SashGrid.STORAGE_CLOSED, '[]');
    localStorage.setItem(SashGrid.STORAGE_MINIMIZED, '[]');
    SashGrid.closedWindows = new Set();
    SashGrid.minimizedWindows = new Set();
    SashGrid._applyStates();
  },

  _applyWindowStatesObj(val) {
    localStorage.setItem(SashGrid.STORAGE_CLOSED, JSON.stringify(val.closed||[]));
    localStorage.setItem(SashGrid.STORAGE_MINIMIZED, JSON.stringify(val.minimized||[]));
    SashGrid.closedWindows = new Set((val.closed||[]).filter(id=>SashCore.WINDOW_IDS.includes(id)));
    SashGrid.minimizedWindows = new Set((val.minimized||[]).filter(id=>SashCore.WINDOW_IDS.includes(id) && !SashGrid.closedWindows.has(id)));
    SashGrid._applyStates();
  },

  _handleWindowStates(result, isEmpty) {
    if (typeof SashGrid === 'undefined') return;
    try {
      if (isEmpty) this._clearWindowStates();
      else if (result.value && typeof result.value === 'object') this._applyWindowStatesObj(result.value);
    } catch (e) {}
  },

  _handleUrls(result, isEmpty) {
    if (typeof UrlList === 'undefined') return;
    const list = isEmpty ? [] : (Array.isArray(result.value) ? result.value : []);
    UrlList.render(list.map(v=>({
      id: v.id, url: v.url, enabled: v.enabled, status: v.status||v.last_status||'pending', last_error: v.last_error||v.error||''
    })));
    if (App.state) App.state.urls = list;
  },

  _handleFolder(result, isEmpty) {
    if (typeof FolderPicker === 'undefined') return;
    if (App.state) {
      App.state.folder = isEmpty ? { root_path: '', supported_types: ['.png','.jpg','.jpeg','.webp'], ignore_ai_suffix: true } : result.value;
      FolderPicker.restore(App.state);
    }
  },

  _handleQueue(result, isEmpty) {
    if (typeof ImageQueue === 'undefined') return;
    if (App.state) {
      const list = isEmpty ? [] : result.value;
      if (Array.isArray(list)) { ImageQueue.render(list); App.state.images = list; }
    }
  },

  _handlePrompt(result, isEmpty) {
    if (typeof PromptEditor === 'undefined') return;
    const tmpl = isEmpty ? '' : (typeof result.value === 'string' ? result.value : (result.value.template || result.value.user_prompt || ''));
    const ta = document.getElementById('promptTextarea');
    if (ta) ta.value = tmpl;
    PromptEditor.updatePreview();
    if (App.state?.prompt) App.state.prompt.template = tmpl;
  },

  _handleSettings(result, isEmpty) {
    if (typeof SettingsPanel === 'undefined') return;
    if (App.state && !isEmpty) { App.state.settings = result.value; SettingsPanel.restore(App.state); }
  },

  _handleArena(result, isEmpty) {
    if (!App.state) return;
    if (isEmpty) return;
    try { this._applyArenaParts(result.value); } catch (e) { console.warn('arena restore failed', e); }
  },

  _applyArenaParts(val) {
    if (!val) return;
    if (val.urls) UrlList.render(val.urls);
    if (val.folder) FolderPicker.restore({folder:val.folder, images: val.images||App.state.images});
    if (val.images) ImageQueue.render(val.images);
    if (val.prompt) PromptEditor.restore({prompt:val.prompt});
    if (val.settings) SettingsPanel.restore({settings:val.settings});
    if (val.progress) ProgressPanel.update(val.progress);
  },

  _applyGlobalKind(result) {
    const kind = result.kind;
    const isEmpty = this._isEmptyResult(result);
    const map = {
      grid: () => this._handleGrid(result, isEmpty),
      window_states: () => this._handleWindowStates(result, isEmpty),
      urls: () => this._handleUrls(result, isEmpty),
      folder: () => this._handleFolder(result, isEmpty),
      queue: () => this._handleQueue(result, isEmpty),
      prompt: () => this._handlePrompt(result, isEmpty),
      settings: () => this._handleSettings(result, isEmpty),
      arena: () => this._handleArena(result, isEmpty),
    };
    if (map[kind]) map[kind]();
    if (typeof LogConsole !== 'undefined') LogConsole.log(`↩ Undo/Redo applied: ${kind}`, 'info');
  },

  _syncGlobalHistory() {
    if (!App.bridge || !App.bridge.get_undo_history) return;
    App.bridge.get_undo_history((json) => {
      try {
        const state = JSON.parse(json);
        if (state && Array.isArray(state.history)) {
          this.globalHistory = state.history
            .filter(e => e && this.UNDO_KINDS.includes(e.kind))
            .map(e => ({ kind: e.kind, value: this._copy(e.value) }));
          this.globalHistoryIndex = Number.isInteger(state.index) ? state.index : this.globalHistory.length - 1;
          this._updateUndoButtons();
        }
      } catch (e) {}
    });
  },

  undoGlobal() {
    if (!App.bridge || !App.bridge.undo) return false;
    App.bridge.undo((raw) => {
      if (!this._applyGlobalResult(raw)) {
        if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Nothing to undo', 'warn');
      }
    });
    return true;
  },

  redoGlobal() {
    if (!App.bridge || !App.bridge.redo) return false;
    App.bridge.redo((raw) => {
      if (!raw || raw === 'null') {
        if (typeof LogConsole !== 'undefined') LogConsole.log('⚠ Nothing to redo', 'warn');
      } else {
        this._applyGlobalResult(raw);
      }
    });
    return true;
  },

  _updateUndoButtons() {
    const undo = document.getElementById('undoBtn');
    const redo = document.getElementById('redoBtn');
    const canUndo = this.globalHistoryIndex >= 0;
    const canRedo = this.globalHistory.length > 0 && this.globalHistoryIndex < this.globalHistory.length - 1;
    if (undo) {
      undo.disabled = !canUndo;
      undo.title = canUndo ? `Undo ${this.globalHistory[this.globalHistoryIndex]?.kind||''} (Ctrl+Z) — ${this.globalHistoryIndex+1}/${this.globalHistory.length}` : 'Nothing to undo';
    }
    if (redo) {
      redo.disabled = !canRedo;
      redo.title = canRedo ? `Redo ${this.globalHistory[this.globalHistoryIndex+1]?.kind||''} (Ctrl+Y) — ${this.globalHistoryIndex+2}/${this.globalHistory.length}` : 'Nothing to redo';
    }
    const badge = document.getElementById('undoCountBadge');
    if (badge) badge.textContent = `${this.globalHistoryIndex+1}/${this.globalHistory.length}`;
  },

  onUndoStateChanged(json) {
    try {
      const data = JSON.parse(json);
      if (data && Array.isArray(data.history)) {
        this.globalHistory = data.history;
        this.globalHistoryIndex = data.index;
        this._updateUndoButtons();
      }
    } catch (e) {}
  }
};

if (typeof window !== 'undefined') {
  window.ArenaHistory = ArenaHistory;
  window.AppHistory = ArenaHistory;
}

/* arena-history.js — global undo/redo timeline for Arena Image Processor
   Reuses old app-history.js pattern but with arena kinds: grid, urls, folder, queue, prompt, settings, window_states, arena
*/

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
    if (!history.length && state.history && Array.isArray(state.history)) {
      history = state.history;
    }
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
      try {
        App.bridge.push_global_history(kind, JSON.stringify(value));
      } catch (e) {
        console.warn('push_global_history failed', e);
      }
    }
  },

  _applyGlobalResult(raw) {
    if (!raw || raw === 'null') return false;
    let result;
    try { result = JSON.parse(raw); } catch (e) { return false; }
    if (!result || !result.kind) {
      return false;
    }
    if (Number.isInteger(result.index)) this.globalHistoryIndex = result.index;
    // If undo went to empty (index -1, value null, empty flag), handle specially
    if (result.index === -1 && (result.empty || result.value === null || result.value === undefined)) {
      const undone = result.undone || {};
      const undoneKind = undone.kind || result.kind;
      if (undoneKind === 'grid' && typeof SashGrid !== 'undefined') {
        // Apply default tree when grid undone to empty
        try {
          if (typeof SashCore !== 'undefined' && SashCore.defaultTree) {
            SashGrid.root = SashCore.defaultTree();
            SashGrid.render();
            try { localStorage.setItem(SashGrid.STORAGE_KEY, SashCore.serialize(SashGrid.root)); } catch (e) {}
          }
        } catch (e) {}
        if (typeof LogConsole !== 'undefined') LogConsole.log('↩ Undo grid → default', 'info');
        this._updateUndoButtons();
        return true;
      }
      // For other kinds, let _applyGlobalKind handle empty (e.g. clear urls)
      // Fall through to _applyGlobalKind with undone kind but empty value
      const emptyResult = { kind: undoneKind, value: result.value, index: -1, empty: true, undone: undone };
      this._applyGlobalKind(emptyResult);
      this._updateUndoButtons();
      return true;
    }
    this._applyGlobalKind(result);
    this._updateUndoButtons();
    return true;
  },

  _applyGlobalKind(result) {
    const kind = result.kind;
    const value = result.value;
    const isEmpty = result.empty || value === null || value === undefined;
    if (kind === 'grid' && typeof SashGrid !== 'undefined') {
      if (isEmpty) {
        // empty grid -> default
        try {
          if (typeof SashCore !== 'undefined' && SashCore.defaultTree) {
            SashGrid.root = SashCore.defaultTree();
            SashGrid.render();
            try { localStorage.setItem(SashGrid.STORAGE_KEY, SashCore.serialize(SashGrid.root)); } catch (e) {}
          }
        } catch (e) {}
      } else {
        SashGrid._applySerialized(value, false);
      }
    } else if (kind === 'window_states' && typeof SashGrid !== 'undefined') {
      try {
        if (isEmpty) {
          localStorage.setItem(SashGrid.STORAGE_CLOSED, '[]');
          localStorage.setItem(SashGrid.STORAGE_MINIMIZED, '[]');
          SashGrid.closedWindows = new Set();
          SashGrid.minimizedWindows = new Set();
          SashGrid._applyStates();
        } else if (value && typeof value === 'object') {
          localStorage.setItem(SashGrid.STORAGE_CLOSED, JSON.stringify(value.closed||[]));
          localStorage.setItem(SashGrid.STORAGE_MINIMIZED, JSON.stringify(value.minimized||[]));
          SashGrid.closedWindows = new Set((value.closed||[]).filter(id=>SashCore.WINDOW_IDS.includes(id)));
          SashGrid.minimizedWindows = new Set((value.minimized||[]).filter(id=>SashCore.WINDOW_IDS.includes(id) && !SashGrid.closedWindows.has(id)));
          SashGrid._applyStates();
        }
      } catch (e) {}
    } else if (kind === 'urls' && typeof UrlList !== 'undefined') {
      const list = isEmpty ? [] : (Array.isArray(value) ? value : []);
      UrlList.render(list.map(v=>({
        id: v.id, url: v.url, enabled: v.enabled, status: v.status||v.last_status||'pending', last_error: v.last_error||v.error||''
      })));
      if (App.state) App.state.urls = list;
    } else if (kind === 'folder' && typeof FolderPicker !== 'undefined') {
      if (App.state) {
        App.state.folder = isEmpty ? { root_path: '', supported_types: ['.png','.jpg','.jpeg','.webp'], ignore_ai_suffix: true } : value;
        FolderPicker.restore(App.state);
      }
    } else if (kind === 'queue' && typeof ImageQueue !== 'undefined') {
      if (App.state) {
        const list = isEmpty ? [] : value;
        if (Array.isArray(list)) {
          ImageQueue.render(list);
          App.state.images = list;
        }
      }
    } else if (kind === 'prompt' && typeof PromptEditor !== 'undefined') {
      const tmpl = isEmpty ? '' : (typeof value === 'string' ? value : (value.template || value.user_prompt || ''));
      const ta = document.getElementById('promptTextarea');
      if (ta) ta.value = tmpl;
      PromptEditor.updatePreview();
      if (App.state && App.state.prompt) App.state.prompt.template = tmpl;
    } else if (kind === 'settings' && typeof SettingsPanel !== 'undefined') {
      if (App.state && !isEmpty) {
        App.state.settings = value;
        SettingsPanel.restore(App.state);
      }
    } else if (kind === 'arena' && App.state) {
      try {
        if (isEmpty) {
          // clear arena? keep as is
        } else {
          if (value.urls) UrlList.render(value.urls);
          if (value.folder) FolderPicker.restore({folder:value.folder, images: value.images||App.state.images});
          if (value.images) ImageQueue.render(value.images);
          if (value.prompt) PromptEditor.restore({prompt:value.prompt});
          if (value.settings) SettingsPanel.restore({settings:value.settings});
          if (value.progress) ProgressPanel.update(value.progress);
        }
      } catch (e) { console.warn('arena restore failed', e); }
    }
    if (typeof LogConsole !== 'undefined') {
      LogConsole.log(`↩ Undo/Redo applied: ${kind}`, 'info');
    }
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
    // update header badges if exist
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

// Also expose as AppHistory for compatibility with old sash-grid code that calls App.recordGlobal
if (typeof window !== 'undefined') {
  window.ArenaHistory = ArenaHistory;
  // compatibility alias
  window.AppHistory = ArenaHistory;
}

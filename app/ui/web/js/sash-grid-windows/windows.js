/* sash-grid-windows/windows.js — window open/close/minimize, ≤150 LOC */
'use strict';
window.SashGridWindows = {
  showAllWindows() {
    this.closedWindows.clear();
    this.minimizedWindows.clear();
    Object.values(this.winEls).forEach((panel) => {
      if (!panel) return;
      panel.classList.remove('hidden');
      if (panel.style.display === 'none') panel.style.display = '';
    });
    this._saveWindowStates();
    this._applyStates();
  },

  resetToDefault() {
    this.root = SashCore.defaultTree();
    this.closedWindows.clear();
    this.minimizedWindows.clear();
    this.showAllWindows();
    this.render();
    let saved = false;
    try {
      if (typeof App !== 'undefined' && App.bridge && App.bridge.reset_grid_layout) {
        App.bridge.reset_grid_layout((raw) => { if (raw) this._applySerialized(raw, true); });
        saved = true;
      }
    } catch {}
    if (!saved) this._save();
    this._saveWindowStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('↺ Grid layout reset to default — all windows visible', 'info');
    return true;
  },

  setLayout(name) {
    const fn = SashCore.PRESETS[name];
    if (!fn) return false;
    this.root = fn();
    this.render();
    this._save();
    if (typeof LogConsole !== 'undefined') {
      const label = { default: 'Default', a: 'A — stacked rows', b: 'B — split top row', c: 'C — side column' }[name] || name;
      LogConsole.log('📐 Layout \"' + label + '\" applied', 'info');
    }
    return true;
  },

  isClosed(id) { return this.closedWindows.has(id); },
  isMinimized(id) { return this.minimizedWindows.has(id); },

  closeWindow(id) {
    if (!SashCore.WINDOW_IDS.includes(id)) return false;
    if (this.closedWindows.has(id)) return false;
    this.closedWindows.add(id);
    this.minimizedWindows.delete(id);
    const panel = this.winEls[id];
    if (panel) panel.classList.add('hidden');
    this._saveWindowStates();
    this._applyStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('🪟 Closed ' + (SashCore.WINDOW_TITLES[id] || id), 'info');
    return true;
  },

  openWindow(id) {
    if (!SashCore.WINDOW_IDS.includes(id)) return false;
    if (!this.closedWindows.has(id)) return false;
    this.closedWindows.delete(id);
    const panel = this.winEls[id];
    if (panel) {
      panel.classList.remove('hidden');
      if (panel.style.display === 'none') panel.style.display = '';
    }
    this._saveWindowStates();
    this._applyStates();
    this._flashLanded(id);
    if (typeof LogConsole !== 'undefined') LogConsole.log('🪟 Opened ' + (SashCore.WINDOW_TITLES[id] || id), 'success');
    return true;
  },

  showWindow(winId) {
    if (!SashCore.WINDOW_IDS.includes(winId)) return false;
    if (this.closedWindows.has(winId)) return this.openWindow(winId);
    if (this.minimizedWindows.has(winId)) return this.restoreMinimized(winId);
    const panel = this.winEls[winId];
    if (!panel) return false;
    panel.classList.remove('hidden');
    if (panel.style.display === 'none') panel.style.display = '';
    this._syncHidden();
    this._syncEmptySplits();
    this._syncSashes();
    this._checkEmptyGrid();
    return true;
  },

  toggleWindow(id) {
    if (this.isClosed(id)) return this.openWindow(id);
    if (this.isMinimized(id)) return this.restoreMinimized(id);
    return this.closeWindow(id);
  },

  minimizeWindow(id) {
    if (!SashCore.WINDOW_IDS.includes(id)) return false;
    if (this.isClosed(id)) return false;
    if (this.isMinimized(id)) return false;
    this.minimizedWindows.add(id);
    this._saveWindowStates();
    this._applyStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('🗕 Minimized ' + (SashCore.WINDOW_TITLES[id] || id) + ' — docked', 'info');
    return true;
  },

  restoreMinimized(id) {
    if (!this.isMinimized(id)) return false;
    this.minimizedWindows.delete(id);
    this._saveWindowStates();
    this._applyStates();
    this._flashLanded(id);
    if (typeof LogConsole !== 'undefined') LogConsole.log('🗖 Restored ' + (SashCore.WINDOW_TITLES[id] || id), 'success');
    return true;
  },

  toggleMinimize(id) {
    if (this.isMinimized(id)) return this.restoreMinimized(id);
    return this.minimizeWindow(id);
  },
};

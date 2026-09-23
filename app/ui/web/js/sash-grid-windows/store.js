/* sash-grid-windows/store.js — window store + states, ≤150 LOC, CC≤10 */
'use strict';
window.SashGridWindowStore = {
  _collectPanels() {
    const winElIds = {
      url_list: 'winUrlList', folder: 'winFolder', queue: 'winQueue', prompt: 'winPrompt',
      run: 'winRun', progress: 'winProgress', watcher: 'winWatcher', log: 'winLog',
      settings: 'winSettings', captcha: 'winCaptcha', recordings: 'winCaptchaRecords',
      browser: 'winBrowser', action_blocks: 'winActionBlocks', block_config: 'winBlockConfig',
      arena_presets: 'winArenaPresets', live_debug: 'winLiveDebug', job_history: 'winJobHistory', firefox_auto: 'winFirefoxAuto',
    };
    for (const w of SashCore.WINDOWS) {
      const el = document.getElementById(winElIds[w.id]);
      if (!el) { console.warn('sash-grid: panel for \"' + w.id + '\" missing'); continue; }
      this.winEls[w.id] = el;
    }
  },

  _loadTree() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (!raw) return null;
      const res = SashCore.deserialize(raw);
      if (res.ok) return res.tree;
      console.warn('sash-grid: persisted layout rejected (' + res.error + ') — using default');
      return null;
    } catch { return null; }
  },

  _parseIds(raw) {
    try {
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      return arr.filter(id => typeof id === 'string' && SashCore.WINDOW_IDS.includes(id));
    } catch { return []; }
  },

  _loadClosed() {
    const raw = localStorage.getItem(this.STORAGE_CLOSED);
    if (!raw) return;
    this._parseIds(raw).forEach(id => this.closedWindows.add(id));
  },

  _loadMinimized() {
    const raw = localStorage.getItem(this.STORAGE_MINIMIZED);
    if (!raw) return;
    this._parseIds(raw).forEach(id => {
      if (!this.closedWindows.has(id)) this.minimizedWindows.add(id);
    });
  },

  _loadWindowStates() {
    try { this._loadClosed(); } catch {}
    try { this._loadMinimized(); } catch {}
  },

  _saveWindowStates() {
    try {
      localStorage.setItem(this.STORAGE_CLOSED, JSON.stringify(Array.from(this.closedWindows)));
      localStorage.setItem(this.STORAGE_MINIMIZED, JSON.stringify(Array.from(this.minimizedWindows)));
    } catch {}
    try {
      if (typeof App !== 'undefined' && App.bridge && App.bridge.save_window_states) {
        const payload = JSON.stringify({ closed: Array.from(this.closedWindows), minimized: Array.from(this.minimizedWindows) });
        App.bridge.save_window_states(payload);
      }
    } catch {}
  },

  _save() {
    const payload = SashCore.serialize(this.root);
    try { localStorage.setItem(this.STORAGE_KEY, payload); } catch {}
    try {
      if (typeof App !== 'undefined' && App.bridge && App.bridge.save_grid_layout) {
        App.bridge.save_grid_layout(payload);
        return;
      }
    } catch {}
    if (typeof App !== 'undefined' && App.recordGlobal) App.recordGlobal('grid', payload, { localOnly: true });
  },

  _onGridFromBackend(raw) {
    if (!raw) return;
    const res = SashCore.deserialize(raw);
    if (!res.ok) return;
    if (raw === SashCore.serialize(this.root)) return;
    this.root = res.tree;
    this.render();
  },

  _onStatesFromBackend(raw) {
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      if (!data || typeof data !== 'object') return;
      if (Array.isArray(data.closed)) this.closedWindows = new Set(data.closed.filter((id) => SashCore.WINDOW_IDS.includes(id)));
      if (Array.isArray(data.minimized)) this.minimizedWindows = new Set(data.minimized.filter((id) => SashCore.WINDOW_IDS.includes(id) && !this.closedWindows.has(id)));
      this.render();
      this._saveWindowStates();
    } catch {}
  },

  _loadFromBackend() {
    try {
      if (typeof App === 'undefined' || !App.bridge) return;
      if (App.bridge.get_grid_layout) App.bridge.get_grid_layout((raw) => this._onGridFromBackend(raw));
      if (App.bridge.get_window_states) App.bridge.get_window_states((raw) => this._onStatesFromBackend(raw));
    } catch {}
  },

  _applySerialized(raw, showAll) {
    if (!raw || raw === 'null') return false;
    const res = SashCore.deserialize(raw);
    if (!res.ok) return false;
    this.root = res.tree;
    if (showAll) this.showAllWindows();
    this.render();
    try { localStorage.setItem(this.STORAGE_KEY, raw); } catch {}
    return true;
  },
};

/* sash-grid part — sash-grid-presets.js (Round H, H-A3) */

const SashGridPresets = {
  _screenSnapshot(rect) {
    const width = (typeof window !== 'undefined' && window.innerWidth) || rect.width || 1;
    const height = (typeof window !== 'undefined' && window.innerHeight) || rect.height || 1;
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    return { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)),
      device_pixel_ratio: Number(dpr) || 1 };
  },

  _portableBounds(id, gridRect, screen) {
    const panel = this.winEls[id];
    const rect = panel && typeof panel.getBoundingClientRect === 'function'
      ? panel.getBoundingClientRect() : { left: gridRect.left, top: gridRect.top, width: 0, height: 0 };
    const width = Math.max(1, gridRect.width || screen.width);
    const height = Math.max(1, gridRect.height || screen.height);
    const clamp = (value) => Math.max(0, Math.min(1, Number(value) || 0));
    const w = clamp(rect.width / width), h = clamp(rect.height / height);
    return { x: clamp((rect.left - gridRect.left) / width), y: clamp((rect.top - gridRect.top) / height),
      width: w, height: h };
  },

  _collectClosed(states, rect, screen) {
    const closed = states.closed.slice();
    SashCore.WINDOW_IDS.forEach((id) => {
      const panel = this.winEls[id];
      if (closed.includes(id)) return;
      if (states.minimized.includes(id)) return;
      if (!panel) return;
      if (!this._panelIsHidden(panel)) return;
      closed.push(id);
    });
    return closed;
  },

  _buildWindows(effectiveStates, rect, screen) {
    return SashCore.WINDOWS.map((item) => {
      const state = effectiveStates.closed.includes(item.id) ? 'closed'
        : (effectiveStates.minimized.includes(item.id) ? 'minimized' : 'open');
      return { id: item.id, title: item.title, state,
        bounds: this._portableBounds(item.id, rect, screen) };
    });
  },

  createPortablePreset(name) {
    const rect = this.gridEl && this.gridEl.getBoundingClientRect
      ? this.gridEl.getBoundingClientRect() : { left: 0, top: 0, width: 1, height: 1 };
    const screen = this._screenSnapshot(rect);
    const states = this.getWindowStates();
    const closed = this._collectClosed(states, rect, screen);
    const effectiveStates = { closed, minimized: states.minimized.slice() };
    const windows = this._buildWindows(effectiveStates, rect, screen);
    const now = new Date().toISOString();
    return { format: this.PRESET_FORMAT, schema_version: this.PRESET_SCHEMA_VERSION,
      app_version: this.APP_VERSION, name: String(name || '').trim() || 'Untitled preset',
      created_at: now, updated_at: now,
      grid: { type: 'sash-tree', version: SashCore.VERSION, window_count: windows.length,
        sizes_unit: 'percent', tree: SashCore.clone(this.root) },
      windows, window_states: effectiveStates, screen };
  },

  _portableStates(doc) {
    const state = doc.window_states;
    if (!state || !Array.isArray(state.closed) || !Array.isArray(state.minimized))
      return { ok: false, error: 'window_states must contain closed and minimized lists' };
    const known = (id) => typeof id === 'string' && SashCore.WINDOW_IDS.includes(id);
    if (!state.closed.every(known) || !state.minimized.every(known))
      return { ok: false, error: 'window_states contains an unknown window' };
    if (new Set(state.closed).size !== state.closed.length || new Set(state.minimized).size !== state.minimized.length)
      return { ok: false, error: 'window_states contains a duplicate window' };
    if (state.closed.some((id) => state.minimized.includes(id)))
      return { ok: false, error: 'closed and minimized window states overlap' };
    return { ok: true, states: { closed: state.closed.slice(), minimized: state.minimized.slice() } };
  },

  _checkWindowItem(item, states, seen) {
    if (!item || typeof item.id !== 'string') return 'windows contain an unknown or duplicate id';
    if (seen.has(item.id)) return 'windows contain an unknown or duplicate id';
    if (!SashCore.WINDOW_IDS.includes(item.id)) return 'windows contain an unknown or duplicate id';
    const wanted = states.closed.includes(item.id) ? 'closed'
      : (states.minimized.includes(item.id) ? 'minimized' : 'open');
    if (item.state !== wanted) return 'window state or normalized bounds are invalid';
    if (!this._validPortableBounds(item.bounds)) return 'window state or normalized bounds are invalid';
    return null;
  },

  _portableWindows(doc, states) {
    if (!Array.isArray(doc.windows) || doc.windows.length !== SashCore.WINDOW_IDS.length)
      return { ok: false, error: 'windows do not contain the current window set' };
    const seen = new Set();
    for (const item of doc.windows) {
      const err = this._checkWindowItem(item, states, seen);
      if (err) return { ok: false, error: err };
      seen.add(item.id);
    }
    if (seen.size !== SashCore.WINDOW_IDS.length)
      return { ok: false, error: 'windows do not contain the current window set' };
    return { ok: true };
  },

  _validPortableBounds(bounds) {
    if (!bounds || typeof bounds !== 'object') return false;
    const values = ['x', 'y', 'width', 'height'].map((key) => bounds[key]);
    if (!values.every((value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1)) return false;
    return bounds.x + bounds.width <= 1.001 && bounds.y + bounds.height <= 1.001;
  },

  _extractDpr(screen) {
    if (!screen) return null;
    const dpr = screen.device_pixel_ratio === undefined ? 1 : screen.device_pixel_ratio;
    if (typeof dpr !== 'number' || !Number.isFinite(dpr) || dpr <= 0) return null;
    return dpr;
  },

  _screenSizeValid(screen) {
    if (!screen) return false;
    if (typeof screen.width !== 'number' || !Number.isFinite(screen.width)) return false;
    if (typeof screen.height !== 'number' || !Number.isFinite(screen.height)) return false;
    if (screen.width <= 0 || screen.height <= 0) return false;
    return true;
  },

  _portableScreen(doc) {
    const screen = doc.screen;
    if (!this._screenSizeValid(screen)) return null;
    return this._extractDpr(screen);
  },

  _cleanPortablePreset(doc, treeResult) {
    const dpr = this._portableScreen(doc);
    if (dpr === null) return { ok: false, error: 'screen metadata is invalid' };
    const clean = SashCore.clone(doc);
    clean.name = clean.name.trim();
    clean.app_version = clean.app_version.trim();
    clean.screen.device_pixel_ratio = dpr;
    clean.grid.tree = treeResult.tree;
    clean.grid.version = SashCore.VERSION;
    return { ok: true, document: clean,
      warning: clean.app_version === this.APP_VERSION ? '' : 'preset was created by app ' + clean.app_version };
  },

  _parseRaw(raw) {
    try { return { ok: true, doc: typeof raw === 'string' ? JSON.parse(raw) : SashCore.clone(raw) }; }
    catch (e) { return { ok: false, error: 'bad JSON: ' + e.message }; }
  },

  _checkFormat(doc) {
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return 'document must be an object';
    if (doc.format !== this.PRESET_FORMAT || doc.schema_version !== this.PRESET_SCHEMA_VERSION)
      return 'unsupported window preset format or schema version';
    return null;
  },

  _checkVersionAndName(doc) {
    if (typeof doc.app_version !== 'string' || !doc.app_version.trim()) return 'app_version is required';
    if (typeof doc.name !== 'string' || !doc.name.trim() || doc.name.trim().length > 80)
      return 'preset name must be 1–80 characters';
    return null;
  },

  _checkGridMeta(doc) {
    const grid = doc.grid;
    if (!grid || grid.type !== 'sash-tree' || grid.sizes_unit !== 'percent' || grid.window_count !== SashCore.WINDOW_IDS.length)
      return 'grid metadata is invalid';
    return null;
  },

  _validateDocMeta(doc) {
    let err = this._checkFormat(doc);
    if (err) return err;
    err = this._checkVersionAndName(doc);
    if (err) return err;
    return this._checkGridMeta(doc);
  },

  validatePortablePreset(raw) {
    const parsed = this._parseRaw(raw);
    if (!parsed.ok) return parsed;
    const doc = parsed.doc;
    const metaErr = this._validateDocMeta(doc);
    if (metaErr) return { ok: false, error: metaErr };
    const treeResult = SashCore.deserialize(JSON.stringify({ v: doc.grid.version, tree: doc.grid.tree }));
    if (!treeResult.ok) return { ok: false, error: 'invalid grid tree: ' + treeResult.error };
    const stateResult = this._portableStates(doc);
    if (!stateResult.ok) return stateResult;
    const windowResult = this._portableWindows(doc, stateResult.states);
    if (!windowResult.ok) return windowResult;
    return this._cleanPortablePreset(doc, treeResult);
  },

  _restoreWinElsVisibility() {
    Object.values(this.winEls).forEach((panel) => {
      if (!panel) return;
      panel.classList.remove('hidden');
      if (panel.style && panel.style.display === 'none') panel.style.display = '';
    });
  },

  applyPortablePreset(raw) {
    const result = this.validatePortablePreset(raw);
    if (!result.ok) {
      if (typeof LogConsole !== 'undefined') LogConsole.log('❌ Window preset not applied: ' + result.error, 'error');
      return false;
    }
    const doc = result.document;
    this.root = SashCore.clone(doc.grid.tree);
    this.closedWindows = new Set(doc.window_states.closed);
    this.minimizedWindows = new Set(doc.window_states.minimized);
    this._restoreWinElsVisibility();
    this.render();
    this._save();
    this._saveWindowStates();
    if (typeof LogConsole !== 'undefined') LogConsole.log('✅ Window preset “' + doc.name + '” restored', 'success');
    return true;
  },
};

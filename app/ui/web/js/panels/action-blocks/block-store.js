/* block-store.js — data layer for Action Blocks (C7)
   Holds blocks, catalogs, job state and persistence helpers.
   RULE18: file 150-300, func ≤30, CC≤10

   2026-10-02 bugfix: QWebChannel slot calls are asynchronous — a call
   without a callback returns undefined, so the old synchronous
   `bridge.get_action_blocks()` never yielded data and the panel silently
   painted local defaults while the backend could hold an EMPTY stack.
   The store now (a) accepts blocks only through `_acceptBlocks`
   (shape-checked, empty → defaults), (b) loads via callback when the
   bridge is async, (c) exposes `restoreDefaults(cb)` which calls the
   backend's restore_default_blocks (fallback reset_action_blocks) once.
   B11 (2026-10-07): the catalog / custom-block / stack-preset loads take
   the same callback path (they were still synchronous → always empty).
*/
'use strict';

window.ActionBlocksStore = {
  blocks: [],
  builtinCatalog: [],
  customBlocks: [],
  stackPresets: [],
  _lastStackPreset: '',
  jobStatuses: {},
  jobOrder: [],
  currentJobId: null,
  selectedIdx: -1,

  _blockDefs() {
    return {
      CUSTOM_FIND: { name: 'Find & Click', icon: 'search', color: '#ff2d2d', category: 'action', description: 'Generic visual click' },
      OBSERVE_BASELINE: { name: 'Observe Baseline', icon: 'visibility', color: '#5AA9FF', category: 'observe', required: true },
      CHECK_SECURITY: { name: 'Check Security Verification Dialog', icon: 'captcha', color: '#FF6B6B', category: 'security', description: 'Detect CAPTCHA pause' },
      HIGHLIGHT_ATTACH: { name: 'Highlight Attach Input', icon: 'highlight', color: '#4ADE80', category: 'visual' },
      ATTACH_IMAGE: { name: 'Attach Image', icon: 'attach_file', color: '#00FF00', category: 'action', required: true },
      VERIFY_ATTACHMENT: { name: 'Verify Attachment', icon: 'fact_check', color: '#00FF00', category: 'verify' },
      HIGHLIGHT_PROMPT: { name: 'Highlight Prompt', icon: 'highlight', color: '#00AAFF', category: 'visual' },
      INSERT_PROMPT: { name: 'Insert Prompt', icon: 'edit', color: '#00AAFF', category: 'action', required: true },
      VERIFY_PROMPT: { name: 'Verify Prompt', icon: 'verified', color: '#00AAFF', category: 'verify' },
      HIGHLIGHT_SUBMIT: { name: 'Highlight Submit', icon: 'highlight', color: '#FFAA00', category: 'visual' },
      SUBMIT: { name: 'Submit Once', icon: 'send', color: '#FFAA00', category: 'action', required: true },
      WAIT_OUTPUT: { name: 'Wait New Output', icon: 'hourglass_top', color: '#00c853', category: 'wait', required: true },
      AWAIT_PROCESSING_IMAGE: { name: 'Wait for Image to Finish Generating', icon: 'await_result', color: '#FFAA00', category: 'process', description: 'Waiting block' },
      DOWNLOAD: { name: 'Download HQ', icon: 'download', color: '#00FFAA', category: 'action', required: true },
      VALIDATE: { name: 'Validate Image', icon: 'verified', color: '#00FFAA', category: 'verify', required: true },
      SAVE: { name: 'Save *_AI.ext', icon: 'save', color: '#4ADE80', category: 'persist', required: true },
      ADVANCE: { name: 'Advance & Persist', icon: 'check_circle', color: '#4ADE80', category: 'persist', required: true },
      PAUSE: { name: 'Custom Pause', icon: 'pause', color: '#888888', category: 'control' },
      HIGHLIGHT: { name: 'Highlight Only', icon: 'center_focus_strong', color: '#00c853', category: 'visual' },
    };
  },

  _blockOrder() {
    return ['HIGHLIGHT_ATTACH', 'OBSERVE_BASELINE', 'CHECK_SECURITY', 'AWAIT_PROCESSING_IMAGE', 'ATTACH_IMAGE', 'VERIFY_ATTACHMENT', 'HIGHLIGHT_PROMPT', 'INSERT_PROMPT', 'VERIFY_PROMPT', 'HIGHLIGHT_SUBMIT', 'SUBMIT', 'WAIT_OUTPUT', 'DOWNLOAD', 'VALIDATE', 'SAVE', 'ADVANCE'];
  },

  _baseBlockFields(bt, idx, d) {
    return {
      id: `${bt.toLowerCase()}_${idx}`,
      block_id: bt,
      name: d.name || bt,
      description: d.description || '',
      icon: d.icon || 'extension',
      color: d.color || '#888',
      category: d.category || 'action',
      required: !!d.required,
      enabled: true,
    };
  },

  _timingFields(isWait) {
    return {
      timeout_ms: isWait ? 180000 : 10000,
      highlight_ms: 2000,
      highlight_duration_ms: 2000,
      pre_delay_ms: 200,
      confirm_pause_ms: 700,
    };
  },

  _makeDefaultBlock(bt, idx, defs) {
    const d = defs[bt] || {};
    const isWait = d.category === 'wait' || d.category === 'process';
    return {
      ...this._baseBlockFields(bt, idx, d),
      selector: '',
      label_selector: '',
      match_text: '',
      match_mode: 'contains',
      click_enabled: true,
      click_selector: '',
      fallback_selector: '',
      fallback_text: '',
      highlight_enabled: true,
      ...this._timingFields(isWait),
      custom_name: '',
      extra: {},
    };
  },

  getDefaultBlocks() {
    const defs = this._blockDefs();
    const order = this._blockOrder();
    return order.map((bt, idx) => this._makeDefaultBlock(bt, idx, defs));
  },

  _selectorDefaults(b) {
    return {
      selector: b.selector || '',
      label_selector: b.label_selector || '',
      match_text: b.match_text || '',
      match_mode: b.match_mode || 'contains',
      click_enabled: b.click_enabled !== false,
      click_selector: b.click_selector || '',
      fallback_selector: b.fallback_selector || '',
      fallback_text: b.fallback_text || '',
    };
  },

  _visualDefaults(b) {
    return {
      highlight_enabled: b.highlight_enabled !== false,
      color: b.color || '#FF0000',
      timeout_ms: b.timeout_ms || 10000,
      pre_delay_ms: b.pre_delay_ms || 200,
      highlight_ms: b.highlight_ms || 2000,
      confirm_pause_ms: b.confirm_pause_ms || 700,
      enabled: b.enabled !== false,
    };
  },

  _catalogEntryFromBlock(b) {
    return {
      block_id: b.block_id,
      name: b.name,
      icon: b.icon,
      description: b.description || '',
      category: b.category,
      required: !!b.required,
      allow_duplicate: ['CUSTOM_FIND', 'PAUSE', 'HIGHLIGHT', 'AWAIT_PROCESSING_IMAGE'].includes(b.block_id),
      defaults: { ...this._selectorDefaults(b), ...this._visualDefaults(b) },
      labels: {},
    };
  },

  _buildFallbackCatalog() {
    if (this.builtinCatalog.length) return;
    this.builtinCatalog = this.getDefaultBlocks().map(b => this._catalogEntryFromBlock(b));
  },

  loadBuiltin(onLoaded) {
    this._buildFallbackCatalog();
    this._loadJsonArray('get_builtin_blocks', 'builtinCatalog', onLoaded);
  },

  /** Adopt a non-empty JSON array reply into this[targetKey]; cb(list) once adopted. */
  _adoptList(res, targetKey, onLoaded) {
    let data = res;
    try { data = typeof res === 'string' ? JSON.parse(res) : res; } catch (e) { console.warn(`${targetKey} parse failed`, e); return; }
    if (!Array.isArray(data) || !data.length) return;
    this[targetKey] = data;
    if (typeof onLoaded === 'function') onLoaded(data);
  },

  /** Async-safe list load: `slot(cb)` for QWebChannel, sync shim for tests. */
  _loadJsonArray(bridgeFnName, targetKey, onLoaded) {
    const bridge = window.App && window.App.bridge;
    if (!bridge || !bridge[bridgeFnName]) return;
    const adopt = (res) => this._adoptList(res, targetKey, onLoaded);
    try {
      const res = bridge[bridgeFnName](adopt);
      if (typeof res === 'string') adopt(res);
    } catch (e) { console.warn(`${bridgeFnName} failed`, e); }
  },

  loadCustom(onLoaded) { this._loadJsonArray('get_custom_blocks', 'customBlocks', onLoaded); },
  loadStackPresets(onLoaded) { this._loadJsonArray('get_stack_presets', 'stackPresets', onLoaded); },

  _looksValid(data) {
    return Array.isArray(data) && data.length > 0 &&
      data.every(b => b && typeof b === 'object' && typeof b.block_id === 'string' && b.block_id);
  },

  /** The ONE way blocks enter the store: valid array → adopt; anything else → defaults. */
  _acceptBlocks(data) {
    let parsed = data;
    if (typeof parsed === 'string') {
      try { parsed = parsed.trim() ? JSON.parse(parsed) : []; } catch (e) { console.warn('blocks parse failed', e); parsed = null; }
    }
    this.blocks = this._looksValid(parsed) ? parsed : this.getDefaultBlocks();
    return this.blocks;
  },

  load(onLoaded) {
    const bridge = window.App && window.App.bridge;
    const done = () => { if (typeof onLoaded === 'function') onLoaded(this.blocks); };
    if (!bridge || !bridge.get_action_blocks) { this._acceptBlocks(null); done(); return; }
    try {
      const res = bridge.get_action_blocks((async) => { this._acceptBlocks(async); done(); });
      if (typeof res === 'string') { this._acceptBlocks(res); done(); }  // sync shim (tests/standalone)
    } catch (e) { console.warn('get_action_blocks failed', e); this._acceptBlocks(null); done(); }
  },

  save() {
    const bridge = window.App && window.App.bridge;
    if (!bridge || !bridge.save_action_blocks) return;
    if (!this._looksValid(this.blocks)) { console.warn('refusing to save an invalid/empty stack'); return; }
    try { bridge.save_action_blocks(JSON.stringify(this.blocks)); } catch {}
  },

  _blocksFromReply(payload) {
    let data = payload;
    try { data = typeof payload === 'string' ? JSON.parse(payload) : payload; } catch { return null; }
    return data && Array.isArray(data.blocks) ? data.blocks : null;
  },

  _adoptRestored(payload, cb) {
    const blocks = this._blocksFromReply(payload);
    this.selectedIdx = -1;
    if (blocks) { this._acceptBlocks(blocks); if (cb) cb(this.blocks); return; }
    this.load(() => { if (cb) cb(this.blocks); });   // reply without blocks (reset_action_blocks) → reload
  },

  _restoreLocally(cb) {
    this._acceptBlocks(null);
    this.selectedIdx = -1;
    this.save();
    if (cb) cb(this.blocks);
  },

  /** Backend-authoritative reset; cb(blocks) after the store adopted the reply. */
  restoreDefaults(cb) {
    const bridge = window.App && window.App.bridge;
    const slot = bridge && (bridge.restore_default_blocks || bridge.reset_action_blocks);
    if (!slot) { this._restoreLocally(cb); return; }
    try {
      const res = slot.call(bridge, (payload) => this._adoptRestored(payload, cb));
      if (typeof res === 'string') this._adoptRestored(res, cb);  // sync shim
    } catch (e) { console.warn('restore defaults failed', e); this._restoreLocally(cb); }
  },

  moveBlock(fromIdx, toIdx) {
    if (fromIdx === toIdx) return;
    const block = this.blocks.splice(fromIdx, 1)[0];
    this.blocks.splice(toIdx, 0, block);
    this.selectedIdx = toIdx;
    this.save();
  },

  toggleBlock(blockId, enabled) {
    const b = this.blocks.find(x => x.id === blockId);
    if (!b) return;
    if (b.required && !enabled) return;
    b.enabled = enabled;
    this.save();
  },

  deleteBlock(blockId) {
    const idx = this.blocks.findIndex(b => b.id === blockId);
    if (idx === -1) return null;
    const block = this.blocks[idx];
    if (block.required) return null;
    this.blocks.splice(idx, 1);
    if (this.selectedIdx === idx) this.selectedIdx = -1;
    else if (this.selectedIdx > idx) this.selectedIdx--;
    this.save();
    return block;
  },

  addCustomBlock(entry) {
    if (!entry || !entry.block) return;
    const newBlock = { ...entry.block, id: `${entry.block.block_id.toLowerCase()}_${Date.now()}` };
    this.blocks.push(newBlock);
    this.save();
    return newBlock;
  },

  saveBlockAsCustom(block, name) {
    if (!block) return null;
    const toSave = { ...block, custom_name: name };
    const entry = { name, block: toSave, updated_at: new Date().toISOString() };
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.save_custom_block) {
      try { bridge.save_custom_block(JSON.stringify(entry)); } catch {}
    }
    this.customBlocks = this.customBlocks.filter(c => c.name !== name);
    this.customBlocks.push(entry);
    return entry;
  },

  deleteCustomBlock(name) {
    this.customBlocks = this.customBlocks.filter(c => c.name !== name);
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.delete_custom_block) {
      try { bridge.delete_custom_block(name); } catch {}
    }
  },

  saveStackPreset(name) {
    const entry = { name, blocks: JSON.parse(JSON.stringify(this.blocks)) };
    this.stackPresets = this.stackPresets.filter(c => c.name !== name);
    this.stackPresets.push(entry);
    this._lastStackPreset = name;
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.save_stack_preset) {
      try { bridge.save_stack_preset(JSON.stringify(entry)); } catch {}
    }
    return entry;
  },

  loadStackPreset(entry) {
    if (!entry || !Array.isArray(entry.blocks) || !entry.blocks.length) return;
    this.blocks = JSON.parse(JSON.stringify(entry.blocks));
    this.selectedIdx = -1;
    this.save();
  },

  deleteStackPreset(name) {
    this.stackPresets = this.stackPresets.filter(c => c.name !== name);
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.delete_stack_preset) {
      try { bridge.delete_stack_preset(name); } catch {}
    }
  },
};

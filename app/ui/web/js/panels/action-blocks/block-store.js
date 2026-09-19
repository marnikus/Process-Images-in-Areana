/* block-store.js — data layer for Action Blocks (C7)
   Holds blocks, catalogs, job state and persistence helpers.
   RULE18: file 150-300, func ≤30, CC≤10
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

  _tryLoadBuiltinFromBridge() {
    const bridge = window.App && window.App.bridge;
    if (!bridge || !bridge.get_builtin_blocks) return false;
    try {
      const res = bridge.get_builtin_blocks();
      if (typeof res !== 'string') return false;
      const data = JSON.parse(res);
      if (!Array.isArray(data)) return false;
      this.builtinCatalog = data;
      return true;
    } catch {
      return false;
    }
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

  _catalogDefaults(b) {
    return { ...this._selectorDefaults(b), ...this._visualDefaults(b) };
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
      defaults: this._catalogDefaults(b),
      labels: {},
    };
  },

  _buildFallbackCatalog() {
    if (this.builtinCatalog.length) return;
    this.builtinCatalog = this.getDefaultBlocks().map(b => this._catalogEntryFromBlock(b));
  },

  loadBuiltin() {
    this._tryLoadBuiltinFromBridge();
    this._buildFallbackCatalog();
  },

  _loadJsonArray(bridgeFnName, targetKey) {
    const bridge = window.App && window.App.bridge;
    if (!bridge || !bridge[bridgeFnName]) return;
    try {
      const res = bridge[bridgeFnName]();
      if (typeof res !== 'string') return;
      const data = JSON.parse(res);
      if (Array.isArray(data)) this[targetKey] = data;
    } catch {}
  },

  loadCustom() { this._loadJsonArray('get_custom_blocks', 'customBlocks'); },
  loadStackPresets() { this._loadJsonArray('get_stack_presets', 'stackPresets'); },

  load() {
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.get_action_blocks) {
      try {
        const res = bridge.get_action_blocks();
        if (typeof res === 'string' && res.trim()) {
          const data = JSON.parse(res);
          if (Array.isArray(data) && data.length > 0) {
            this.blocks = data;
            return;
          }
        }
      } catch (e) { console.warn('parse failed', e); }
    }
    this.blocks = this.getDefaultBlocks();
  },

  save() {
    const bridge = window.App && window.App.bridge;
    if (!bridge || !bridge.save_action_blocks) return;
    try { bridge.save_action_blocks(JSON.stringify(this.blocks)); } catch {}
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

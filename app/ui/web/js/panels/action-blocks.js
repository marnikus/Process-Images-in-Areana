/* action-blocks.js — facade C14 ≤300 LOC, delegates to store/fields/render/views/config/listeners/ui/status/io
   B11 (2026-10-07): render/config modules now speak the real index.html DOM
   (#actionBlocksStack, #blockConfigHead/#blockConfigForm, #jobActionStack,
   #allJobsStack, #customBlockChips, #stackPresetChips). */
'use strict';

const ActionBlocksPanel = {
  _store: null, _render: null, _config: null, _listeners: null, _ui: null, _status: null, _io: null, _views: null,
  _bridgeUnsubs: [], _dragSrc: null, _isPaused: false, _pauseReason: '', _saveTimer: null,

  get blocks() { return this._store.blocks; }, set blocks(v) { this._store.blocks = v; },
  get builtinCatalog() { return this._store.builtinCatalog; },
  get customBlocks() { return this._store.customBlocks; },
  get stackPresets() { return this._store.stackPresets; },
  get jobStatuses() { return this._store.jobStatuses; },
  get jobOrder() { return this._store.jobOrder; },
  get currentJobId() { return this._store.currentJobId; }, set currentJobId(v) { this._store.currentJobId = v; },
  get selectedIdx() { return this._store.selectedIdx; }, set selectedIdx(v) { this._store.selectedIdx = v; },

  init() {
    this._store = window.ActionBlocksStore; this._render = window.ActionBlocksRender; this._views = window.ActionBlocksViews;
    this._config = window.ActionBlocksConfig; this._listeners = window.ActionBlocksListeners; this._ui = window.ActionBlocksUI;
    this._status = window.ActionBlocksStatus; this._io = window.ActionBlocksIO;
    this.loadBuiltin(); this.loadCustom(); this.loadStackPresets();
    this._store.load(() => this.render());
    this._config.bindFormEvents(() => this.blocks[this.selectedIdx], () => this.save());
    this.bindUI(); this.ensurePauseOverlay(); this.tryBindBridge(); this.attachGlobalHandlers(); this.render();
  },

  _confirm(text, onYes) {
    if (window.Dialog?.confirm) { window.Dialog.confirm('Action Blocks', text, 'OK', onYes); return; }
    if (typeof confirm !== 'function' || confirm(text)) onYes();
  },

  _prompt(title, initial, onOk) {
    if (window.Dialog?.promptEdit) { window.Dialog.promptEdit(title, initial || '', 'OK', onOk); return; }
    const v = typeof prompt === 'function' ? prompt(title, initial) : initial;
    if (v) onOk(v);
  },

  tryBindBridge() {
    if (window.App?.bridge) this.bindBridgeSignals();
    else {
      const check = setInterval(() => {
        if (window.App?.bridge) { this.bindBridgeSignals(); clearInterval(check); }
      }, 500);
    }
  },

  attachGlobalHandlers() { this._ui.attachGlobalHandlers(this); },
  ensurePauseOverlay() { this._ui.ensurePauseOverlay(); },
  setPaused(p,r) { this._status.setPaused(this,p,r); },
  handleKeydown(e) { this._ui.handleKeydown(this,e); },

  bindUI() {
    const map = {
      addActionBlockBtn: () => this.showAddDialog(),
      resetActionBlocksBtn: () => this.resetToDefault(),
      saveActionBlocksBtn: () => this.saveAsPreset(),
      exportActionBlocksBtn: () => this.export(),
      importActionBlocksBtn: () => this.import(),
      saveCustomBlockBtn: () => this.saveSelectedAsCustom(),
      abRunBtn: () => this.triggerRun(),
      closeBlockConfigBtn: () => this.deselect(),
    };
    Object.keys(map).forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      if (window.Boot) window.Boot.bindOnce(el, 'click', map[id], `action-blocks:${id}`);
      else el.addEventListener('click', map[id]);
    });
  },

  triggerRun() {
    const bridge = window.App?.bridge;
    if (bridge?.start_run) { try { bridge.start_run(); } catch {} }
    document.getElementById('runStartBtn')?.click();
  },

  bindBridgeSignals() {
    const bridge = window.App?.bridge;
    if (!bridge) return;
    try { if (this._listeners) this._bridgeUnsubs = this._listeners.bindBridge(this); } catch (e) { console.warn('bindBridge failed', e); }
  },

  loadBuiltin() { this._store.loadBuiltin(() => this.showConfig(this.selectedIdx, true)); },
  loadCustom() { this._store.loadCustom(() => this.renderCustomChips()); },
  loadStackPresets() { this._store.loadStackPresets(() => this.renderStackChips()); },
  load() { this._store.load(() => this.render()); this.render(); },
  getDefaultBlocks() { return this._store.getDefaultBlocks(); },

  onBlocksUpdated(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      if (!Array.isArray(data)) return;
      this.blocks = data.length === 0 ? this.getDefaultBlocks() : data;
      this.render();
    } catch {}
  },

  onJobStarted(id) { this._status.onJobStarted(this,id); this._render.clearRowStatuses(); },
  onJobActionStatus(j,b,s) { this._status.onJobActionStatus(this,j,b,s); this._render.markRowStatus(b, this._statusOf(j,b)); },
  onJobFinished(id) { this._status.onJobFinished(this,id); },
  onJobPaused(r) { this._status.onJobPaused(this,r); },
  onJobResumed() { this._status.onJobResumed(this); },
  onJobFailed(id) { this._status.onJobFailed(this,id); },
  onCustomBlocksUpdated() { this.loadCustom(); },
  onStackPresetsUpdated() { this.loadStackPresets(); },
  _statusOf(jobId, blockId) {
    const st = (this.jobStatuses[jobId] || {})[blockId];
    return st ? (typeof st === 'string' ? st : st.status) : null;
  },

  _listHandlers() {
    return {
      onSelect: (idx) => this.selectBlock(idx),
      onToggle: (id,en) => this.toggleBlock(id,en),
      onConfig: (idx) => this.selectBlock(idx),
      onDelete: (id) => this.deleteBlock(id),
      onHighlight: (b) => this.highlightBlock(b),
      onDragStart: (e,idx) => { this._dragSrc=idx; if (e.dataTransfer) e.dataTransfer.effectAllowed='move'; },
      onDragOver: (e) => { e.preventDefault(); },
      onDrop: (e,idx) => { e.preventDefault(); if (this._dragSrc!==null && this._dragSrc!==idx) this.moveBlock(this._dragSrc,idx); this._dragSrc=null; },
      onDragEnd: () => { this._dragSrc=null; },
    };
  },

  render() {
    const state = { selectedIdx: this.selectedIdx, jobStatuses: this.jobStatuses, currentJobId: this.currentJobId, blocks: this.blocks };
    this._render.renderBlockList(this.blocks, state, this._listHandlers());
    this.renderCustomChips(); this.renderStackChips(); this.updateFooter();
    this.showConfig(this.selectedIdx, false);
    this.renderJobStack(this.currentJobId); this.renderAllJobs();
  },

  highlightBlock(block) {
    if (!block || !block.selector || !window.HighlightOverlay?.highlightViaCDP) return;
    window.HighlightOverlay.highlightViaCDP(block.selector, block.color, block.highlight_ms, this._render.displayName(block));
  },
  renderCustomChips() {
    this._views.renderChips('customBlockChips', this.customBlocks, { emptyText: 'No custom presets yet — select a CUSTOM_FIND block and press "Save Custom preset"',
      meta: (e) => (e.block && e.block.block_id) || '', tooltip: 'Click to add to stack', onLoad: (e)=>this.addCustomBlock(e), onDelete: (n)=>this.deleteCustomBlock(n) });
  },
  renderStackChips() {
    this._views.renderChips('stackPresetChips', this.stackPresets, { emptyText: 'No stack presets yet — press Save to store the current stack',
      meta: (e) => `${(e.blocks || []).length} blocks`, tooltip: 'Click to load (replaces current stack)', onLoad: (e)=>this.loadStackPreset(e), onDelete: (n)=>this.deleteStackPreset(n) });
  },
  renderJobStack(jobId) {
    this._views.renderJobStack({ jobId, blocks: this.blocks, statuses: this.jobStatuses, onRect: (b)=>this.highlightBlock(b) });
  },
  renderAllJobs() {
    this._views.renderAllJobs({ jobOrder: this.jobOrder, currentJobId: this.currentJobId, jobStatuses: this.jobStatuses, onSelectJob: (jid)=>{ this.currentJobId=jid; this.render(); } });
  },
  updateFooter() { this._views.updateFooter(this.blocks); },

  selectBlock(idx) {
    if (idx===null || idx<0 || idx>=this.blocks.length) { this.deselect(); return; }
    this.selectedIdx=idx; this.render(); this.showConfig(idx, true);
  },
  deselect() { this.selectedIdx=-1; this.showConfig(null, true); this.render(); },
  _labelsFor(block) {
    const entry = block ? this.builtinCatalog.find(c => c.block_id === block.block_id) : null;
    return (entry && entry.labels) || {};
  },
  showConfig(idx, force) {
    const block = idx === null || idx < 0 ? null : (this.blocks[idx] || null);
    this._config.showConfig(block, this._labelsFor(block), !!force);
  },

  moveBlock(f,t) { this._store.moveBlock(f,t); this.render(); },
  toggleBlock(id,en) { this._store.toggleBlock(id,en); this.render(); },
  deleteBlock(blockId) {
    const b = this.blocks.find(x=>x.id===blockId);
    if (b?.required) return;
    this._confirm(`Delete block ${b ? (b.custom_name||b.name) : blockId}?`, () => { this._store.deleteBlock(blockId); this.render(); });
  },
  addBuiltinBlock(blockId) {
    const bridge = window.App?.bridge;
    if (bridge?.add_action_block) {
      try { bridge.add_action_block(blockId); this.load(); return; } catch {}
    }
    const def = this.getDefaultBlocks().find(b=>b.block_id===blockId);
    if (def) { this.blocks.push({ ...def, id: `${blockId.toLowerCase()}_${Date.now()}` }); this.save(); this.render(); }
  },
  showAddDialog() {
    const existing = new Set(this.blocks.map(b=>b.block_id));
    const avail = this.builtinCatalog.length ? this.builtinCatalog : this.getDefaultBlocks().map(b=>({ block_id:b.block_id, name:b.name, allow_duplicate:['CUSTOM_FIND','PAUSE','HIGHLIGHT','AWAIT_PROCESSING_IMAGE'].includes(b.block_id) }));
    const choices = avail.filter(bt=>bt.allow_duplicate || !existing.has(bt.block_id));
    if (!choices.length) { LogConsole.log('Action Blocks: all block types are already in the stack', 'warn'); return; }
    const list = choices.map(c=>c.block_id).join(', ');
    this._prompt(`Add block — one of: ${list}`, choices[0].block_id, (bt) => this.addBuiltinBlock(bt.trim().toUpperCase()));
  },
  resetToDefault() {
    this._confirm('Reset action blocks to default?', () => this._store.restoreDefaults(() => this.render()));
  },

  save() { this._io.save(this); },
  saveDebouncedPush() { this._io.saveDebouncedPush(this); },
  export() { this._io.exportBlocks(this.blocks); },
  import() { this._io.importBlocks(this, (data)=>{ this.blocks=data; this.save(); this.render(); }); },

  addCustomBlock(entry) { this._store.addCustomBlock(entry); this.render(); },
  deleteCustomBlock(name) { this._confirm(`Delete custom block "${name}"?`, () => { this._store.deleteCustomBlock(name); this.renderCustomChips(); }); },
  saveBlockAsCustom(block) {
    if (!block) return;
    this._prompt('Save custom block as preset — name:', block.custom_name||block.name||'Custom',
      (name) => { this._store.saveBlockAsCustom(block,name); this.renderCustomChips(); });
  },
  saveSelectedAsCustom() { if (this.selectedIdx<0) return; this.saveBlockAsCustom(this.blocks[this.selectedIdx]); },
  saveAsPreset() {
    if (!this.blocks.length) return;
    this._prompt('Save full stack as preset — name:', this._store._lastStackPreset||'My stack',
      (name) => { this._store.saveStackPreset(name); this.renderStackChips(); });
  },
  loadStackPreset(entry) { this._store.loadStackPreset(entry); this.render(); },
  deleteStackPreset(name) { this._confirm(`Delete stack preset "${name}"?`, () => { this._store.deleteStackPreset(name); this.renderStackChips(); }); },
};

if (typeof window !== 'undefined') window.ActionBlocksPanel = ActionBlocksPanel;

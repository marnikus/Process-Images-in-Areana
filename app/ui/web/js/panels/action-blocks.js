/* action-blocks.js — facade C14 ≤300 LOC, delegates to store/render/config/listeners/ui/status/io */
'use strict';

const ActionBlocksPanel = {
  _store: null, _render: null, _config: null, _listeners: null, _ui: null, _status: null, _io: null,
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
    this._store = window.ActionBlocksStore;
    this._render = window.ActionBlocksRender;
    this._config = window.ActionBlocksConfig;
    this._listeners = window.ActionBlocksListeners;
    this._ui = window.ActionBlocksUI;
    this._status = window.ActionBlocksStatus;
    this._io = window.ActionBlocksIO;
    this._store.loadBuiltin(); this._store.loadCustom(); this._store.loadStackPresets(); this._store.load();
    this.bindUI(); this.ensurePauseOverlay(); this.tryBindBridge(); this.attachGlobalHandlers(); this.render();
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
  _cleanSashLeftovers() { this._ui._cleanSashLeftovers(); },
  _cleanupDragState() { this._ui._cleanupDragState(this); },
  ensurePauseOverlay() { this._ui.ensurePauseOverlay(); },
  _updateBadge(p,r) { this._status._updateBadge(p,r); },
  _updateCorner(p,r) { this._status._updateCorner(p,r); },
  _updateStatus(p,r) { this._status._updateStatus(p,r); },
  setPaused(p,r) { this._status.setPaused(this,p,r); },
  _isCaptchaStatus(s) { return this._status._isCaptchaStatus(s); },
  detectPause(s) { this._status.detectPause(this,s); },
  _ensureJob(id) { this._status._ensureJob(this,id); },
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
      if (el) el.addEventListener('click', map[id]);
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

  loadBuiltin() { this._store.loadBuiltin(); this.renderAddMenu(); },
  loadCustom() { this._store.loadCustom(); this.renderCustomChips(); },
  loadStackPresets() { this._store.loadStackPresets(); this.renderStackChips(); },
  load() { this._store.load(); this.render(); },
  getDefaultBlocks() { return this._store.getDefaultBlocks(); },

  onBlocksUpdated(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      if (!Array.isArray(data)) return;
      this.blocks = data.length === 0 ? this.getDefaultBlocks() : data;
      this.render();
    } catch {}
  },

  onJobStarted(id) { this._status.onJobStarted(this,id); },
  onJobActionStatus(j,b,s) { this._status.onJobActionStatus(this,j,b,s); },
  onJobFinished(id) { this._status.onJobFinished(this,id); },
  onJobPaused(r) { this._status.onJobPaused(this,r); },
  onJobResumed() { this._status.onJobResumed(this); },
  onJobFailed(id) { this._status.onJobFailed(this,id); },
  onCustomBlocksUpdated() { this.loadCustom(); },
  onStackPresetsUpdated() { this.loadStackPresets(); },

  _renderList(root, storeState) {
    this._render.renderBlockList(root, this.blocks, storeState, {
      onSelect: (idx) => this.selectBlock(idx),
      onToggle: (id,en) => this.toggleBlock(id,en),
      onConfig: (idx) => this.selectBlock(idx),
      onDelete: (id) => this.deleteBlock(id),
      onDragStart: (e,idx) => { this._dragSrc=idx; e.dataTransfer.effectAllowed='move'; },
      onDragOver: (e) => { e.preventDefault(); },
      onDrop: (e,idx) => { e.preventDefault(); if (this._dragSrc!==null && this._dragSrc!==idx) this.moveBlock(this._dragSrc,idx); this._dragSrc=null; },
      onDragEnd: () => { this._dragSrc=null; },
    });
  },

  render() {
    const root = document.getElementById('panel-action-blocks') || document;
    const storeState = { selectedIdx: this.selectedIdx, jobStatuses: this.jobStatuses, currentJobId: this.currentJobId, blocks: this.blocks, _isPaused: this._isPaused, _pauseReason: this._pauseReason };
    this._renderList(root, storeState);
    this.renderAddMenu(); this.renderCustomChips(); this.renderStackChips(); this.updateFooter();
    if (this.selectedIdx >=0) this.showConfig(this.selectedIdx); else this.showConfig(null);
    if (this.currentJobId) { this.renderJobStack(this.currentJobId); this.renderAllJobs(); } else this.renderAllJobs();
  },

  renderAddMenu() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderAddMenu(root, this.builtinCatalog, (bid) => this.addBuiltinBlock(bid));
  },
  renderCustomChips() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderCustomChips(root, this.customBlocks, (e)=>this.addCustomBlock(e), (n)=>this.deleteCustomBlock(n));
  },
  renderStackChips() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderStackChips(root, this.stackPresets, (e)=>this.loadStackPreset(e), (n)=>this.deleteStackPreset(n));
  },
  renderJobStack(jobId) {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderJobStack({ root, jobId, blocks: this.blocks, statuses: this.jobStatuses, onBlockClick: ()=>{} });
  },
  renderAllJobs() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderAllJobs({ root, jobOrder: this.jobOrder, currentJobId: this.currentJobId, jobStatuses: this.jobStatuses, onSelectJob: (jid)=>{ this.currentJobId=jid; this.render(); } });
  },
  updateFooter() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.updateFooter(root, { blocks: this.blocks, _isPaused: this._isPaused, _pauseReason: this._pauseReason });
    const totalEl = document.getElementById('abTotalSteps');
    const selEl = document.getElementById('abSelectedSteps');
    const countEl = document.getElementById('actionBlocksCount');
    if (totalEl) totalEl.textContent = `Total: ${this.blocks.length} steps`;
    if (selEl) selEl.textContent = `Selected: ${this.blocks.filter(b=>b.enabled!==false).length} steps`;
    if (countEl) countEl.textContent = `${this.blocks.length} blocks`;
  },

  selectBlock(idx) {
    if (idx===null || idx<0 || idx>=this.blocks.length) { this.selectedIdx=-1; this.showConfig(null); this.render(); return; }
    this.selectedIdx=idx; this.render(); this.showConfig(idx);
  },
  deselect() { this.selectedIdx=-1; this.showConfig(null); this.render(); },
  showConfig(idx) {
    /* The per-block form renders in the Block Config window (#blockConfigForm
       hosts #ab-config-form) — the stack panel root is for list rendering. */
    const root = document.getElementById('blockConfigForm') || document;
    this._config.showConfig(root, idx, this.blocks);
    if (idx!==null) this._config.bindFormEvents(root, ()=>this.blocks[this.selectedIdx], ()=>this.save());
  },

  moveBlock(f,t) { this._store.moveBlock(f,t); this.render(); },
  toggleBlock(id,en) { this._store.toggleBlock(id,en); this.render(); },
  deleteBlock(blockId) {
    const b = this.blocks.find(x=>x.id===blockId);
    if (b?.required) return;
    if (!confirm(`Delete block ${b ? (b.custom_name||b.name) : blockId}?`)) return;
    this._store.deleteBlock(blockId); this.render();
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
    if (!choices.length) { alert('All types already in stack'); return; }
    const list = choices.map(c=>`${c.block_id} — ${c.name}`).join('\n');
    const bt = prompt(`Add block type:\n${list}\n\nEnter block_id:`, choices[0].block_id);
    if (!bt) return;
    this.addBuiltinBlock(bt.trim().toUpperCase());
  },
  resetToDefault() {
    if (!confirm('Reset action blocks to default?')) return;
    const bridge = window.App?.bridge;
    if (bridge?.reset_action_blocks) {
      try { const res=bridge.reset_action_blocks(); if (typeof res==='string') { this.load(); return; } } catch {}
      try { bridge.reset_action_blocks(()=>this.load()); return; } catch {}
    }
    this.blocks=this.getDefaultBlocks(); this.save(); this.render();
  },

  save() { this._io.save(this); },
  saveDebounced() { this.save(); },
  saveDebouncedPush() { this._io.saveDebouncedPush(this); },
  export() { this._io.exportBlocks(this.blocks); },
  import() { this._io.importBlocks(this, (data)=>{ this.blocks=data; this.save(); this.render(); }); },

  addCustomBlock(entry) { this._store.addCustomBlock(entry); this.render(); },
  deleteCustomBlock(name) { if (!confirm(`Delete custom block \"${name}\"?`)) return; this._store.deleteCustomBlock(name); this.renderCustomChips(); },
  saveBlockAsCustom(block) {
    if (!block) return;
    const name = prompt('Save custom block as preset — name:', block.custom_name||block.name||'Custom');
    if (!name) return;
    this._store.saveBlockAsCustom(block,name); this.renderCustomChips();
  },
  saveSelectedAsCustom() { if (this.selectedIdx<0) return; this.saveBlockAsCustom(this.blocks[this.selectedIdx]); },
  saveAsPreset() {
    if (!this.blocks.length) return;
    const name = prompt('Save full stack as preset — name:', this._store._lastStackPreset||'My stack');
    if (!name) return;
    this._store.saveStackPreset(name); this.renderStackChips();
  },
  loadStackPreset(entry) { this._store.loadStackPreset(entry); this.render(); },
  deleteStackPreset(name) { if (!confirm(`Delete stack preset \"${name}\"?`)) return; this._store.deleteStackPreset(name); this.renderStackChips(); },
  esc(s) { return this._render.esc(s); },
  badgeClassForBlock(b) { return this._render.badgeClassForBlock(b); },
};

if (typeof window !== 'undefined') window.ActionBlocksPanel = ActionBlocksPanel;

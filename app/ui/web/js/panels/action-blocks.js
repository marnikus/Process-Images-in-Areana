/* action-blocks.js — facade (C7)
   Delegates to block-store, block-render, block-config, block-listeners.
   RULE18: file 150-300 ideal, ≤500 hard limit, func ≤30, CC≤10 via helpers
   ideal-size: 434 lines reason=facade must keep getter/setter proxies + lifecycle + pause overlay + bridge binding in one place for App compatibility; further split would create circular deps with store/render
 */
'use strict';

const ActionBlocksPanel = {
  _store: null,
  _render: null,
  _config: null,
  _listeners: null,
  _bridgeUnsubs: [],
  _dragSrc: null,
  _isPaused: false,
  _pauseReason: '',
  _saveTimer: null,

  get blocks() { return this._store.blocks; },
  set blocks(v) { this._store.blocks = v; },
  get builtinCatalog() { return this._store.builtinCatalog; },
  get customBlocks() { return this._store.customBlocks; },
  get stackPresets() { return this._store.stackPresets; },
  get jobStatuses() { return this._store.jobStatuses; },
  get jobOrder() { return this._store.jobOrder; },
  get currentJobId() { return this._store.currentJobId; },
  set currentJobId(v) { this._store.currentJobId = v; },
  get selectedIdx() { return this._store.selectedIdx; },
  set selectedIdx(v) { this._store.selectedIdx = v; },

  init() {
    this._store = window.ActionBlocksStore;
    this._render = window.ActionBlocksRender;
    this._config = window.ActionBlocksConfig;
    this._listeners = window.ActionBlocksListeners;
    this._store.loadBuiltin();
    this._store.loadCustom();
    this._store.loadStackPresets();
    this._store.load();
    this.bindUI();
    this.ensurePauseOverlay();
    this.tryBindBridge();
    this.attachGlobalHandlers();
    this.render();
  },

  tryBindBridge() {
    if (window.App && window.App.bridge) this.bindBridgeSignals();
    else {
      const check = setInterval(() => {
        if (window.App && window.App.bridge) {
          this.bindBridgeSignals();
          clearInterval(check);
        }
      }, 500);
    }
  },

  attachGlobalHandlers() {
    window.addEventListener('arena-presets-updated', () => this.load());
    document.addEventListener('keydown', (e) => this.handleKeydown(e));
    window.addEventListener('blur', () => this._cleanupDragState());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) this._cleanupDragState();
    });
    document.addEventListener('pointerup', () => this._cleanSashLeftovers());
  },

  _cleanSashLeftovers() {
    try {
      const body = document.body;
      const needsClean = body.classList.contains('sash-dragging') || body.classList.contains('sash-resizing-row');
      if (!needsClean) return;
      const sg = window.SashGrid;
      if (!sg || (!sg._drag && !sg._resize)) {
        body.classList.remove('sash-dragging', 'sash-resizing-row', 'sash-resizing-col');
      }
    } catch {}
  },

  _cleanupDragState() {
    try {
      this._dragSrc = null;
      const cont = document.getElementById('actionBlocksStack');
      if (cont) cont.querySelectorAll('.action-block').forEach(el => el.classList.remove('dragging', 'drag-over'));
      document.body.classList.remove('sash-dragging', 'sash-resizing-row', 'sash-resizing-col');
      document.querySelectorAll('.sash-active').forEach(el => el.classList.remove('sash-active'));
      document.querySelectorAll('.sash-drag-clone, .sash-drag-ghost').forEach(el => { if (el.parentNode) el.parentNode.removeChild(el); });
    } catch {}
  },

  ensurePauseOverlay() {
    if (document.getElementById('pauseCornerOverlay')) return;
    const div = document.createElement('div');
    div.id = 'pauseCornerOverlay';
    div.innerHTML = '<span class="material-icons">hourglass_top</span><div><div style="font-size:12px;">ON PAUSE</div><div id="pauseCornerReason" style="font-size:10px; opacity:0.8;">Captcha detected</div></div>';
    document.body.appendChild(div);
  },

  _updateBadge(paused, reason) {
    const badge = document.getElementById('abPauseBadge');
    if (!badge) return;
    badge.classList.toggle('hidden', !paused);
    if (paused) badge.title = reason || 'Paused';
  },

  _updateCorner(paused, reason) {
    const corner = document.getElementById('pauseCornerOverlay');
    if (!corner) return;
    corner.classList.toggle('visible', !!paused);
    const reasonEl = document.getElementById('pauseCornerReason');
    if (reasonEl) reasonEl.textContent = reason || 'Captcha / Security detected';
  },

  _updateStatus(paused, reason) {
    const statusEl = document.getElementById('abStatus');
    if (!statusEl) return;
    statusEl.textContent = paused ? `Status: ON PAUSE — ${reason || 'Captcha'}` : 'Status: Awaiting run command';
    statusEl.style.color = paused ? '#FFAA00' : '';
    statusEl.style.fontWeight = paused ? '700' : '';
  },

  setPaused(paused, reason) {
    this._isPaused = !!paused;
    this._pauseReason = reason || '';
    this._updateBadge(paused, reason);
    this._updateCorner(paused, reason);
    this._updateStatus(paused, reason);
    if (paused && typeof LogConsole !== 'undefined') LogConsole.log(`⏸ ON PAUSE — ${reason || 'Captcha'}`, 'warn');
  },

  handleKeydown(e) {
    if (!e.altKey) return;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    const stack = document.getElementById('actionBlocksStack');
    if (!stack || this.selectedIdx < 0) return;
    e.preventDefault();
    if (e.key === 'ArrowUp' && this.selectedIdx > 0) this.moveBlock(this.selectedIdx, this.selectedIdx - 1);
    if (e.key === 'ArrowDown' && this.selectedIdx < this.blocks.length - 1) this.moveBlock(this.selectedIdx, this.selectedIdx + 1);
  },

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
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.start_run) { try { bridge.start_run(); } catch {} }
    document.getElementById('runStartBtn')?.click();
  },

  bindBridgeSignals() {
    const bridge = window.App && window.App.bridge;
    if (!bridge) return;
    try {
      if (this._listeners) this._bridgeUnsubs = this._listeners.bindBridge(this);
    } catch (e) { console.warn('bindBridge failed', e); }
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

  _ensureJob(jobId) {
    if (this.jobStatuses[jobId]) return;
    this.jobStatuses[jobId] = {};
    this.jobOrder.push(jobId);
    if (this.jobOrder.length > 20) {
      const old = this.jobOrder.shift();
      delete this.jobStatuses[old];
    }
  },

  onJobStarted(jobId) {
    this.currentJobId = jobId;
    this._ensureJob(jobId);
    this.setPaused(false, '');
    this.renderJobStack(jobId);
    this.renderAllJobs();
    this.updateFooter();
  },

  onJobActionStatus(jobId, blockId, statusJson) {
    try {
      const status = typeof statusJson === 'string' ? JSON.parse(statusJson) : statusJson;
      this._ensureJob(jobId);
      this.jobStatuses[jobId][blockId] = status;
      this.currentJobId = jobId;
      this.detectPause(status);
      this.renderJobStack(jobId);
      this.renderAllJobs();
      this.updateFooter();
    } catch {}
  },

  _isCaptchaStatus(status) {
    const name = (status.block_name || '').toLowerCase();
    const msg = (status.message || '').toLowerCase();
    return name.includes('security') || name.includes('captcha') || msg.includes('captcha') || msg.includes('security verification');
  },

  detectPause(status) {
    const isCaptcha = this._isCaptchaStatus(status);
    const isWaiting = ['running', 'waiting', 'paused'].includes(status.status);
    if (isCaptcha && isWaiting) this.setPaused(true, status.message || 'Security Verification');
    if (status.status === 'success' && isCaptcha) this.setPaused(false, '');
  },

  onJobFinished(jobId) {
    this.setPaused(false, '');
    this.renderJobStack(jobId);
    this.renderAllJobs();
    this.updateFooter();
  },

  onJobPaused(reason) { this.setPaused(true, reason); },
  onJobResumed() { this.setPaused(false, ''); },
  onJobFailed(jobId) { this.onJobFinished(jobId); },
  onCustomBlocksUpdated() { this.loadCustom(); },
  onStackPresetsUpdated() { this.loadStackPresets(); },

  render() {
    const root = document.getElementById('panel-action-blocks') || document;
    const storeState = { selectedIdx: this.selectedIdx, jobStatuses: this.jobStatuses, currentJobId: this.currentJobId, blocks: this.blocks, _isPaused: this._isPaused, _pauseReason: this._pauseReason };
    this._render.renderBlockList(root, this.blocks, storeState, {
      onSelect: (idx) => this.selectBlock(idx),
      onToggle: (id, en) => this.toggleBlock(id, en),
      onConfig: (idx) => this.selectBlock(idx),
      onDelete: (id) => this.deleteBlock(id),
      onDragStart: (e, idx) => { this._dragSrc = idx; e.dataTransfer.effectAllowed = 'move'; },
      onDragOver: (e) => { e.preventDefault(); },
      onDrop: (e, idx) => { e.preventDefault(); if (this._dragSrc !== null && this._dragSrc !== idx) this.moveBlock(this._dragSrc, idx); this._dragSrc = null; },
      onDragEnd: () => { this._dragSrc = null; },
    });
    this.renderAddMenu();
    this.renderCustomChips();
    this.renderStackChips();
    this.updateFooter();
    if (this.selectedIdx >= 0) this.showConfig(this.selectedIdx); else this.showConfig(null);
    if (this.currentJobId) { this.renderJobStack(this.currentJobId); this.renderAllJobs(); }
    else this.renderAllJobs();
  },

  renderAddMenu() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderAddMenu(root, this.builtinCatalog, (blockId) => this.addBuiltinBlock(blockId));
  },

  renderCustomChips() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderCustomChips(root, this.customBlocks, (entry) => this.addCustomBlock(entry), (name) => this.deleteCustomBlock(name));
  },

  renderStackChips() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderStackChips(root, this.stackPresets, (entry) => this.loadStackPreset(entry), (name) => this.deleteStackPreset(name));
  },

  renderJobStack(jobId) {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderJobStack({ root, jobId, blocks: this.blocks, statuses: this.jobStatuses, onBlockClick: () => {} });
  },

  renderAllJobs() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.renderAllJobs({ root, jobOrder: this.jobOrder, currentJobId: this.currentJobId, jobStatuses: this.jobStatuses, onSelectJob: (jid) => { this.currentJobId = jid; this.render(); } });
  },

  updateFooter() {
    const root = document.getElementById('panel-action-blocks') || document;
    this._render.updateFooter(root, { blocks: this.blocks, _isPaused: this._isPaused, _pauseReason: this._pauseReason });
    const totalEl = document.getElementById('abTotalSteps');
    const selEl = document.getElementById('abSelectedSteps');
    const countEl = document.getElementById('actionBlocksCount');
    if (totalEl) totalEl.textContent = `Total: ${this.blocks.length} steps`;
    if (selEl) selEl.textContent = `Selected: ${this.blocks.filter(b => b.enabled !== false).length} steps`;
    if (countEl) countEl.textContent = `${this.blocks.length} blocks`;
  },

  selectBlock(idx) {
    if (idx === null || idx < 0 || idx >= this.blocks.length) { this.selectedIdx = -1; this.showConfig(null); this.render(); return; }
    this.selectedIdx = idx;
    this.render();
    this.showConfig(idx);
  },

  deselect() { this.selectedIdx = -1; this.showConfig(null); this.render(); },

  showConfig(idx) {
    const root = document.getElementById('panel-action-blocks') || document;
    this._config.showConfig(root, idx, this.blocks);
    if (idx !== null) this._config.bindFormEvents(root, () => this.blocks[this.selectedIdx], () => this.save());
  },

  moveBlock(fromIdx, toIdx) { this._store.moveBlock(fromIdx, toIdx); this.render(); },
  toggleBlock(blockId, enabled) { this._store.toggleBlock(blockId, enabled); this.render(); },

  deleteBlock(blockId) {
    const b = this.blocks.find(x => x.id === blockId);
    if (b && b.required) return;
    if (!confirm(`Delete block ${b ? (b.custom_name || b.name) : blockId}?`)) return;
    this._store.deleteBlock(blockId);
    this.render();
  },

  addBuiltinBlock(blockId) {
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.add_action_block) {
      try { bridge.add_action_block(blockId); this.load(); return; } catch {}
    }
    const def = this.getDefaultBlocks().find(b => b.block_id === blockId);
    if (def) { this.blocks.push({ ...def, id: `${blockId.toLowerCase()}_${Date.now()}` }); this.save(); this.render(); }
  },

  showAddDialog() {
    const existing = new Set(this.blocks.map(b => b.block_id));
    const avail = this.builtinCatalog.length ? this.builtinCatalog : this.getDefaultBlocks().map(b => ({ block_id: b.block_id, name: b.name, allow_duplicate: ['CUSTOM_FIND','PAUSE','HIGHLIGHT','AWAIT_PROCESSING_IMAGE'].includes(b.block_id) }));
    const choices = avail.filter(bt => bt.allow_duplicate || !existing.has(bt.block_id));
    if (!choices.length) { alert('All types already in stack'); return; }
    const list = choices.map(c => `${c.block_id} — ${c.name}`).join('\n');
    const bt = prompt(`Add block type:\n${list}\n\nEnter block_id:`, choices[0].block_id);
    if (!bt) return;
    this.addBuiltinBlock(bt.trim().toUpperCase());
  },

  resetToDefault() {
    if (!confirm('Reset action blocks to default?')) return;
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.reset_action_blocks) {
      try { const res = bridge.reset_action_blocks(); if (typeof res === 'string') { this.load(); return; } } catch {}
      try { bridge.reset_action_blocks(() => this.load()); return; } catch {}
    }
    this.blocks = this.getDefaultBlocks();
    this.save();
    this.render();
  },

  save() { this._store.save(); this.saveDebouncedPush(); },
  saveDebounced() { this.save(); },

  saveDebouncedPush() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => {
      try {
        const bridge = window.App && window.App.bridge;
        if (bridge && bridge.push_global_history) bridge.push_global_history('action_blocks', JSON.stringify(this.blocks));
      } catch {}
    }, 600);
  },

  export() {
    const payload = JSON.stringify(this.blocks, null, 2);
    const bridge = window.App && window.App.bridge;
    if (bridge && bridge.export_action_blocks) {
      try { const res = bridge.export_action_blocks(payload); if (typeof res === 'string') { this._onExported(res); return; } } catch {}
      try { bridge.export_action_blocks(payload, r => this._onExported(r)); return; } catch {}
    }
    const blob = new Blob([payload], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `arena-action-blocks-${new Date().toISOString().slice(0,10)}.json`; a.click();
    URL.revokeObjectURL(url);
  },

  import() {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.json';
    input.onchange = (e) => {
      const file = e.target.files[0]; if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target.result);
          if (Array.isArray(data)) { this.blocks = data; this.save(); this.render(); }
        } catch {}
      };
      reader.readAsText(file);
    };
    input.click();
  },

  addCustomBlock(entry) { this._store.addCustomBlock(entry); this.render(); },
  deleteCustomBlock(name) { if (!confirm(`Delete custom block "${name}"?`)) return; this._store.deleteCustomBlock(name); this.renderCustomChips(); },
  saveBlockAsCustom(block) {
    if (!block) return;
    const name = prompt('Save custom block as preset — name:', block.custom_name || block.name || 'Custom');
    if (!name) return;
    this._store.saveBlockAsCustom(block, name);
    this.renderCustomChips();
  },
  saveSelectedAsCustom() { if (this.selectedIdx < 0) return; this.saveBlockAsCustom(this.blocks[this.selectedIdx]); },
  saveAsPreset() {
    if (!this.blocks.length) return;
    const name = prompt('Save full stack as preset — name:', this._store._lastStackPreset || 'My stack');
    if (!name) return;
    this._store.saveStackPreset(name);
    this.renderStackChips();
  },
  loadStackPreset(entry) { this._store.loadStackPreset(entry); this.render(); },
  deleteStackPreset(name) { if (!confirm(`Delete stack preset "${name}"?`)) return; this._store.deleteStackPreset(name); this.renderStackChips(); },
  esc(s) { return this._render.esc(s); },
  badgeClassForBlock(b) { return this._render.badgeClassForBlock(b); },
  _onExported(res) {
    try {
      const r = typeof res === 'string' ? JSON.parse(res) : res;
      if (r && r.ok && typeof LogConsole !== 'undefined') LogConsole.log(`📤 Exported to ${r.path || ''}`, 'success');
    } catch {}
  },
};

if (typeof window !== 'undefined') window.ActionBlocksPanel = ActionBlocksPanel;

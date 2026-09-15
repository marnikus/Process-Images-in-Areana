/* action-blocks.js — Stacking jobs as action blocks with visual confirmations, drag & drop reorder, enable/disable, config — restored from old app idea */
'use strict';

const ActionBlocksPanel = {
  blocks: [], // ActionBlock[]
  jobStatuses: {}, // jobId -> { blockId -> {status, message, rect, timestamp} }
  currentJobId: null,
  _dragSrc: null,

  init() {
    this.bindUI();
    this.load();
    // Listen to bridge signals
    if (App.bridge) {
      this.bindBridgeSignals();
    } else {
      // Wait for bridge
      const check = setInterval(() => {
        if (App.bridge) {
          this.bindBridgeSignals();
          clearInterval(check);
        }
      }, 500);
    }
  },

  bindUI() {
    const addBtn = document.getElementById('addActionBlockBtn');
    const resetBtn = document.getElementById('resetActionBlocksBtn');
    const saveBtn = document.getElementById('saveActionBlocksBtn');
    const exportBtn = document.getElementById('exportActionBlocksBtn');
    const importBtn = document.getElementById('importActionBlocksBtn');

    if (addBtn) addBtn.addEventListener('click', () => this.showAddDialog());
    if (resetBtn) resetBtn.addEventListener('click', () => this.resetToDefault());
    if (saveBtn) saveBtn.addEventListener('click', () => this.save());
    if (exportBtn) exportBtn.addEventListener('click', () => this.export());
    if (importBtn) importBtn.addEventListener('click', () => this.import());
  },

  bindBridgeSignals() {
    if (!App.bridge) return;
    try {
      if (App.bridge.action_blocks_updated) {
        App.bridge.action_blocks_updated.connect((payload) => this.onBlocksUpdated(payload));
      }
      if (App.bridge.job_action_status) {
        App.bridge.job_action_status.connect((jobId, blockId, statusJson) => this.onJobActionStatus(jobId, blockId, statusJson));
      }
      if (App.bridge.job_started) {
        App.bridge.job_started.connect((jobId, imagePath) => this.onJobStarted(jobId, imagePath));
      }
      if (App.bridge.job_finished) {
        App.bridge.job_finished.connect((jobId, resultJson) => this.onJobFinished(jobId, resultJson));
      }
    } catch (e) {
      console.warn('ActionBlocks bind signals failed', e);
    }
  },

  load() {
    if (App.bridge && App.bridge.get_action_blocks) {
      try {
        App.bridge.get_action_blocks((res) => {
          try {
            const data = JSON.parse(res);
            if (Array.isArray(data)) {
              this.blocks = data;
              this.render();
            }
          } catch (e) {
            console.warn('parse action blocks failed', e);
          }
        });
      } catch (e) {
        // Try sync version
        try {
          const res = App.bridge.get_action_blocks();
          if (typeof res === 'string') {
            const data = JSON.parse(res);
            if (Array.isArray(data)) {
              this.blocks = data;
              this.render();
            }
          }
        } catch {}
      }
    } else {
      // Fallback default
      this.blocks = this.getDefaultBlocks();
      this.render();
    }
  },

  getDefaultBlocks() {
    // Fallback if backend not ready — mirrors Python DEFAULT_STACK_ORDER
    const defs = {
      OBSERVE_BASELINE: {name: 'Observe Baseline', icon: 'visibility', color: '#888888', category: 'observe', required: true},
      CHECK_SECURITY: {name: 'Check Security Dialog', icon: 'security', color: '#FF6B6B', category: 'observe'},
      HIGHLIGHT_ATTACH: {name: 'Highlight Attach Input', icon: 'highlight', color: '#00FF00', category: 'visual'},
      ATTACH_IMAGE: {name: 'Attach Image', icon: 'attach_file', color: '#00FF00', category: 'action', required: true},
      HIGHLIGHT_PROMPT: {name: 'Highlight Prompt', icon: 'highlight', color: '#00AAFF', category: 'visual'},
      INSERT_PROMPT: {name: 'Insert Prompt', icon: 'edit', color: '#00AAFF', category: 'action', required: true},
      VERIFY_PROMPT: {name: 'Verify Prompt', icon: 'fact_check', color: '#00AAFF', category: 'verify'},
      HIGHLIGHT_SUBMIT: {name: 'Highlight Submit', icon: 'highlight', color: '#FFAA00', category: 'visual'},
      SUBMIT: {name: 'Submit Once', icon: 'send', color: '#FFAA00', category: 'action', required: true},
      WAIT_OUTPUT: {name: 'Wait New Output', icon: 'hourglass_top', color: '#AA00FF', category: 'wait', required: true},
      DOWNLOAD: {name: 'Download Highest Quality', icon: 'download', color: '#00FFAA', category: 'action', required: true},
      VALIDATE: {name: 'Validate Image', icon: 'verified', color: '#00FFAA', category: 'verify', required: true},
      SAVE: {name: 'Save *_AI.ext Atomically', icon: 'save', color: '#4ADE80', category: 'persist', required: true},
      ADVANCE: {name: 'Advance & Persist', icon: 'check_circle', color: '#4ADE80', category: 'persist', required: true},
    };
    const order = Object.keys(defs);
    return order.map((bt, idx) => ({
      id: `${bt.toLowerCase()}_${idx}`,
      block_id: bt,
      name: defs[bt].name,
      icon: defs[bt].icon,
      color: defs[bt].color,
      category: defs[bt].category,
      required: !!defs[bt].required,
      enabled: true,
      selector: '',
      timeout_ms: 30000,
      highlight_duration_ms: 2000,
      pre_delay_ms: 200,
      custom_name: '',
    }));
  },

  onBlocksUpdated(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      if (Array.isArray(data)) {
        this.blocks = data;
        this.render();
        LogConsole.log(`📦 Action blocks updated: ${data.length} blocks`, 'info');
      }
    } catch (e) {
      console.warn('onBlocksUpdated parse failed', e);
    }
  },

  onJobStarted(jobId, imagePath) {
    this.currentJobId = jobId;
    this.jobStatuses[jobId] = {};
    LogConsole.log(`🚀 Job started [${jobId.slice(0,8)}] ${imagePath}`, 'success');
    this.renderJobStack(jobId);
  },

  onJobActionStatus(jobId, blockId, statusJson) {
    try {
      const status = typeof statusJson === 'string' ? JSON.parse(statusJson) : statusJson;
      if (!this.jobStatuses[jobId]) this.jobStatuses[jobId] = {};
      this.jobStatuses[jobId][blockId] = status;
      this.currentJobId = jobId;
      // Log with visual confirmation
      const level = status.status === 'failed' ? 'error' : status.status === 'success' ? 'success' : 'info';
      LogConsole.log(`[${jobId.slice(0,8)}] ${status.block_name || blockId}: ${status.status} ${status.message || ''}`, level);
      // Highlight rect if provided
      if (status.rect && typeof HighlightOverlay !== 'undefined') {
        HighlightOverlay.show({
          x: status.rect.x || 0,
          y: status.rect.y || 0,
          width: status.rect.width || 100,
          height: status.rect.height || 100,
          duration: (status.highlight_duration_ms || 2000) / 1000,
          label: status.block_name || blockId,
          color: status.color || '#FF0000',
        });
      }
      this.renderJobStack(jobId);
    } catch (e) {
      console.warn('onJobActionStatus parse failed', e, statusJson);
    }
  },

  onJobFinished(jobId, resultJson) {
    try {
      const result = typeof resultJson === 'string' ? JSON.parse(resultJson) : resultJson;
      const level = result.status === 'completed' ? 'success' : 'error';
      LogConsole.log(`🏁 Job [${jobId.slice(0,8)}] finished: ${result.status} ${result.message || ''}`, level);
      this.renderJobStack(jobId);
    } catch (e) {}
  },

  render() {
    const container = document.getElementById('actionBlocksStack');
    if (!container) return;
    container.innerHTML = '';
    this.blocks.forEach((block, idx) => {
      const el = this.createBlockElement(block, idx);
      container.appendChild(el);
    });
    // Render current job if any
    if (this.currentJobId) {
      this.renderJobStack(this.currentJobId);
    }
  },

  createBlockElement(block, idx) {
    const div = document.createElement('div');
    div.className = 'action-block';
    div.draggable = true;
    div.dataset.blockId = block.id;
    div.dataset.index = idx;
    const isRequired = !!block.required;
    const enabled = block.enabled !== false;

    div.style.cssText = `
      display:flex; align-items:center; gap:8px; padding:8px 10px; margin:4px 0;
      background: var(--bg-input); border:1px solid ${enabled ? block.color : 'var(--border)'};
      border-left:4px solid ${block.color}; border-radius:6px;
      opacity:${enabled ? '1' : '0.5'}; cursor:grab;
      transition: all 0.15s;
    `;

    const dragHandle = document.createElement('span');
    dragHandle.className = 'material-icons';
    dragHandle.textContent = 'drag_indicator';
    dragHandle.style.cssText = 'font-size:18px; color:var(--text-muted); cursor:grab;';
    dragHandle.title = 'Drag to reorder';

    const icon = document.createElement('span');
    icon.className = 'material-icons';
    icon.textContent = block.icon || 'extension';
    icon.style.cssText = `font-size:18px; color:${block.color};`;

    const info = document.createElement('div');
    info.style.cssText = 'flex:1; min-width:0;';
    const name = document.createElement('div');
    name.textContent = block.custom_name || block.name;
    name.style.cssText = 'font-size:12px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;';
    name.title = block.description || block.name;
    const meta = document.createElement('div');
    meta.textContent = `${block.block_id} • ${block.category}${block.selector ? ' • ' + block.selector.slice(0,30) : ''}`;
    meta.style.cssText = 'font-size:10px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;';
    info.appendChild(name);
    info.appendChild(meta);

    const controls = document.createElement('div');
    controls.style.cssText = 'display:flex; gap:4px; align-items:center;';

    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = enabled;
    toggle.disabled = isRequired;
    toggle.title = isRequired ? 'Required block cannot be disabled' : 'Enable/disable block';
    toggle.addEventListener('change', (e) => {
      block.enabled = e.target.checked;
      this.save();
      this.render();
    });

    const editBtn = document.createElement('button');
    editBtn.className = 'btn-small';
    editBtn.innerHTML = '<span class="material-icons" style="font-size:14px;">edit</span>';
    editBtn.title = 'Edit block';
    editBtn.addEventListener('click', () => this.editBlock(block));

    const delBtn = document.createElement('button');
    delBtn.className = 'btn-small';
    delBtn.innerHTML = '<span class="material-icons" style="font-size:14px;">delete</span>';
    delBtn.title = isRequired ? 'Required block cannot be deleted' : 'Delete block';
    delBtn.disabled = isRequired;
    delBtn.addEventListener('click', () => this.deleteBlock(block.id));

    controls.appendChild(toggle);
    controls.appendChild(editBtn);
    controls.appendChild(delBtn);

    div.appendChild(dragHandle);
    div.appendChild(icon);
    div.appendChild(info);
    div.appendChild(controls);

    // Drag & drop
    div.addEventListener('dragstart', (e) => {
      this._dragSrc = div;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', block.id);
      div.style.opacity = '0.4';
    });
    div.addEventListener('dragend', () => {
      div.style.opacity = enabled ? '1' : '0.5';
      this._dragSrc = null;
      container && (container.querySelectorAll('.action-block').forEach(el => el.style.borderTop = ''));
    });
    div.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (this._dragSrc && this._dragSrc !== div) {
        div.style.borderTop = `2px solid ${block.color}`;
      }
    });
    div.addEventListener('dragleave', () => {
      div.style.borderTop = '';
    });
    div.addEventListener('drop', (e) => {
      e.preventDefault();
      div.style.borderTop = '';
      if (this._dragSrc && this._dragSrc !== div) {
        const srcIdx = parseInt(this._dragSrc.dataset.index);
        const dstIdx = parseInt(div.dataset.index);
        if (!isNaN(srcIdx) && !isNaN(dstIdx)) {
          this.moveBlock(srcIdx, dstIdx);
        }
      }
    });

    // Highlight on click for visual blocks
    if (block.selector) {
      div.addEventListener('dblclick', () => {
        if (App.bridge && App.bridge.highlight_selector) {
          App.bridge.highlight_selector(block.selector, block.color, block.highlight_duration_ms, block.display_name || block.name);
          LogConsole.log(`🔍 Highlighting ${block.selector}`, 'info');
        }
      });
      div.title = `Double-click to highlight: ${block.selector}`;
    }

    return div;
  },

  moveBlock(fromIdx, toIdx) {
    if (fromIdx === toIdx) return;
    const block = this.blocks.splice(fromIdx, 1)[0];
    this.blocks.splice(toIdx, 0, block);
    this.save();
    this.render();
    LogConsole.log(`↕ Moved block ${block.name} from ${fromIdx} to ${toIdx}`, 'info');
  },

  deleteBlock(blockId) {
    const idx = this.blocks.findIndex(b => b.id === blockId);
    if (idx === -1) return;
    const block = this.blocks[idx];
    if (block.required) {
      LogConsole.log(`⚠ Cannot delete required block ${block.name}`, 'warn');
      return;
    }
    this.blocks.splice(idx, 1);
    this.save();
    this.render();
    LogConsole.log(`🗑 Deleted block ${block.name}`, 'warn');
  },

  editBlock(block) {
    const newName = prompt(`Edit custom name for ${block.name}:`, block.custom_name || block.name);
    if (newName === null) return;
    const newSelector = prompt(`Edit selector for ${block.name}:\nCurrent: ${block.selector}`, block.selector);
    if (newSelector === null) return;
    const newColor = prompt(`Edit highlight color (hex) for ${block.name}:`, block.color);
    if (newColor === null) return;
    const newTimeout = prompt(`Edit timeout ms for ${block.name}:`, block.timeout_ms);
    if (newTimeout === null) return;

    if (newName.trim()) block.custom_name = newName.trim();
    block.selector = newSelector.trim();
    if (/^#[0-9A-Fa-f]{3,8}$/.test(newColor.trim())) block.color = newColor.trim();
    const t = parseInt(newTimeout);
    if (!isNaN(t) && t > 0) block.timeout_ms = t;

    this.save();
    this.render();
    LogConsole.log(`✏ Edited block ${block.name}`, 'info');
  },

  showAddDialog() {
    const available = [
      'OBSERVE_BASELINE','CHECK_SECURITY','HIGHLIGHT_ATTACH','ATTACH_IMAGE',
      'HIGHLIGHT_PROMPT','INSERT_PROMPT','VERIFY_PROMPT','HIGHLIGHT_SUBMIT',
      'SUBMIT','WAIT_OUTPUT','DOWNLOAD','VALIDATE','SAVE','ADVANCE'
    ];
    const existing = new Set(this.blocks.map(b => b.block_id));
    const choices = available.filter(bt => !existing.has(bt) || !['OBSERVE_BASELINE','ATTACH_IMAGE','INSERT_PROMPT','SUBMIT','WAIT_OUTPUT','DOWNLOAD','VALIDATE','SAVE','ADVANCE'].includes(bt));
    if (choices.length === 0) {
      alert('All block types already in stack. You can duplicate existing by editing.');
      return;
    }
    const bt = prompt(`Add block type:\nAvailable: ${choices.join(', ')}\n\nEnter block_id:`, choices[0]);
    if (!bt) return;
    const upper = bt.trim().toUpperCase();
    if (!available.includes(upper)) {
      LogConsole.log(`⚠ Unknown block type ${bt}`, 'warn');
      return;
    }
    // Create via backend or local
    if (App.bridge && App.bridge.add_action_block) {
      App.bridge.add_action_block(upper, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`➕ Added block ${upper}`, 'success');
            this.load();
          } else {
            LogConsole.log(`Add failed: ${r.error}`, 'error');
          }
        } catch (e) {}
      });
    } else {
      // Local fallback
      const def = this.getDefaultBlocks().find(b => b.block_id === upper);
      if (def) {
        this.blocks.push({...def, id: `${upper.toLowerCase()}_${Date.now()}`});
        this.save();
        this.render();
      }
    }
  },

  resetToDefault() {
    if (!confirm('Reset action blocks to default stack? This will overwrite current stack.')) return;
    if (App.bridge && App.bridge.reset_action_blocks) {
      App.bridge.reset_action_blocks((res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log('🔄 Action blocks reset to default', 'info');
            this.load();
          }
        } catch {}
      });
    } else {
      this.blocks = this.getDefaultBlocks();
      this.save();
      this.render();
    }
  },

  save() {
    if (App.bridge && App.bridge.save_action_blocks) {
      const payload = JSON.stringify(this.blocks);
      App.bridge.save_action_blocks(payload, (res) => {
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`💾 Saved ${this.blocks.length} action blocks`, 'success');
          } else {
            LogConsole.log(`Save failed: ${r.error}`, 'error');
          }
        } catch {}
      });
    } else {
      LogConsole.log('save_action_blocks not available', 'warn');
    }
  },

  export() {
    const data = JSON.stringify(this.blocks, null, 2);
    const blob = new Blob([data], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `arena-action-blocks-${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    LogConsole.log('📤 Exported action blocks', 'success');
  },

  import() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target.result);
          if (Array.isArray(data)) {
            this.blocks = data;
            this.save();
            this.render();
            LogConsole.log(`📥 Imported ${data.length} action blocks`, 'success');
          } else {
            LogConsole.log('Import failed: not an array', 'error');
          }
        } catch (err) {
          LogConsole.log(`Import failed: ${err}`, 'error');
        }
      };
      reader.readAsText(file);
    };
    input.click();
  },

  renderJobStack(jobId) {
    const container = document.getElementById('jobActionStack');
    if (!container) return;
    const statuses = this.jobStatuses[jobId] || {};
    container.innerHTML = '';

    const title = document.createElement('div');
    title.style.cssText = 'font-size:12px; font-weight:700; margin-bottom:6px; display:flex; justify-content:space-between;';
    title.innerHTML = `<span>Job ${jobId.slice(0,8)} — ${Object.keys(statuses).length}/${this.blocks.length} blocks</span><span style="color:var(--text-muted); font-weight:400;">${new Date().toLocaleTimeString()}</span>`;
    container.appendChild(title);

    this.blocks.forEach((block) => {
      const st = statuses[block.id] || statuses[block.block_id] || {status: 'pending'};
      const row = document.createElement('div');
      const statusColor = st.status === 'success' ? '#4ADE80' : st.status === 'failed' ? '#FF6B6B' : st.status === 'running' ? '#FFAA00' : st.status === 'skipped' ? '#888' : 'var(--border)';
      row.style.cssText = `
        display:flex; align-items:center; gap:6px; padding:4px 6px; margin:2px 0;
        background: var(--bg-input); border:1px solid ${statusColor}; border-left:3px solid ${block.color};
        border-radius:4px; font-size:11px;
      `;
      const icon = document.createElement('span');
      icon.className = 'material-icons';
      icon.style.fontSize = '14px';
      icon.style.color = statusColor;
      const iconMap = {
        pending: 'hourglass_empty',
        running: 'play_circle',
        success: 'check_circle',
        failed: 'error',
        skipped: 'skip_next',
      };
      icon.textContent = iconMap[st.status] || 'circle';

      const name = document.createElement('span');
      name.textContent = block.custom_name || block.name;
      name.style.flex = '1';
      name.title = `${block.block_id}: ${st.message || ''}`;

      const statusText = document.createElement('span');
      statusText.textContent = st.status;
      statusText.style.cssText = `font-size:10px; color:${statusColor}; text-transform:uppercase;`;

      if (st.rect) {
        const rectBtn = document.createElement('button');
        rectBtn.className = 'btn-small';
        rectBtn.innerHTML = '<span class="material-icons" style="font-size:12px;">highlight</span>';
        rectBtn.title = `Show rect ${JSON.stringify(st.rect)}`;
        rectBtn.addEventListener('click', () => {
          if (typeof HighlightOverlay !== 'undefined') {
            HighlightOverlay.show({
              x: st.rect.x, y: st.rect.y, width: st.rect.width, height: st.rect.height,
              duration: 3, label: block.name, color: block.color,
            });
          }
        });
        row.appendChild(rectBtn);
      }

      row.appendChild(icon);
      row.appendChild(name);
      row.appendChild(statusText);
      container.appendChild(row);
    });
  },
};

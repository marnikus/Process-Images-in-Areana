/* action-blocks.js — Stacking jobs with new UI matching target screenshot
   - Larger blocks, full-height resizable stack
   - Drag-drop with animation, shadow, highlight + alt+arrows reorder
   - Waiting & processing states: AWAIT_PROCESSING_IMAGE, CAPTCHA pause visualization
*/

'use strict';

const ActionBlocksPanel = {
  blocks: [],
  builtinCatalog: [],
  customBlocks: [],
  jobStatuses: {},
  jobOrder: [],
  currentJobId: null,
  selectedIdx: -1,
  _dragSrc: null,
  _isPaused: false,
  _pauseReason: '',

  init() {
    this.bindUI();
    this.loadBuiltin();
    this.loadCustom();
    this.load();
    this.ensurePauseOverlay();
    if (window.App && App.bridge) {
      this.bindBridgeSignals();
    } else {
      const check = setInterval(() => {
        if (window.App && App.bridge) {
          this.bindBridgeSignals();
          clearInterval(check);
        }
      }, 500);
    }
    window.addEventListener('arena-presets-updated', () => this.load());
    // Alt+arrows global handler
    document.addEventListener('keydown', (e) => this.handleKeydown(e));
  },

  ensurePauseOverlay() {
    if (document.getElementById('pauseCornerOverlay')) return;
    const div = document.createElement('div');
    div.id = 'pauseCornerOverlay';
    div.innerHTML = `<span class="material-icons">hourglass_top</span><div><div style="font-size:12px;">ON PAUSE</div><div id="pauseCornerReason" style="font-size:10px; opacity:0.8; font-weight:400;">Captcha / Security detected — solve manually</div></div>`;
    document.body.appendChild(div);
  },

  setPaused(paused, reason) {
    this._isPaused = !!paused;
    this._pauseReason = reason || '';
    const badge = document.getElementById('abPauseBadge');
    const corner = document.getElementById('pauseCornerOverlay');
    const reasonEl = document.getElementById('pauseCornerReason');
    if (badge) {
      if (paused) {
        badge.classList.remove('hidden');
        badge.title = reason || 'Paused — captcha / security detected';
      } else badge.classList.add('hidden');
    }
    if (corner) {
      if (paused) {
        corner.classList.add('visible');
        if (reasonEl) reasonEl.textContent = reason || 'Captcha / Security detected — solve manually';
      } else corner.classList.remove('visible');
    }
    const statusEl = document.getElementById('abStatus');
    if (statusEl) {
      statusEl.textContent = paused ? `Status: ON PAUSE — ${reason || 'Captcha detected'}` : 'Status: Awaiting run command';
      statusEl.style.color = paused ? '#FFAA00' : '';
      statusEl.style.fontWeight = paused ? '700' : '';
    }
    if (typeof LogConsole !== 'undefined' && paused) {
      LogConsole.log(`⏸ ON PAUSE — ${reason || 'Captcha / Security detected — waiting for user to solve'}`, 'warn');
    }
  },

  handleKeydown(e) {
    if (!e.altKey) return;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    // Only when action blocks panel focused or block selected
    const stack = document.getElementById('actionBlocksStack');
    if (!stack) return;
    if (this.selectedIdx < 0) return;
    // Check if focus inside panel or just alt+arrows globally when selected
    const active = document.activeElement;
    const inside = stack.contains(active) || document.getElementById('winActionBlocks')?.contains(active);
    // Allow even if not focused, but only if alt pressed — to make discoverable
    if (!inside && !e.altKey) return;
    e.preventDefault();
    if (e.key === 'ArrowUp' && this.selectedIdx > 0) {
      this.moveBlock(this.selectedIdx, this.selectedIdx - 1);
    } else if (e.key === 'ArrowDown' && this.selectedIdx < this.blocks.length - 1) {
      this.moveBlock(this.selectedIdx, this.selectedIdx + 1);
    }
  },

  bindUI() {
    const addBtn = document.getElementById('addActionBlockBtn');
    const resetBtn = document.getElementById('resetActionBlocksBtn');
    const saveBtn = document.getElementById('saveActionBlocksBtn');
    const exportBtn = document.getElementById('exportActionBlocksBtn');
    const importBtn = document.getElementById('importActionBlocksBtn');
    const saveCustomBtn = document.getElementById('saveCustomBlockBtn');
    const runBtn = document.getElementById('abRunBtn');
    if (addBtn) addBtn.addEventListener('click', () => this.showAddDialog());
    if (resetBtn) resetBtn.addEventListener('click', () => this.resetToDefault());
    if (saveBtn) saveBtn.addEventListener('click', () => this.save());
    if (exportBtn) exportBtn.addEventListener('click', () => this.export());
    if (importBtn) importBtn.addEventListener('click', () => this.import());
    if (saveCustomBtn) saveCustomBtn.addEventListener('click', () => this.saveSelectedAsCustom());
    if (runBtn) runBtn.addEventListener('click', () => {
      if (App.bridge && App.bridge.start_run) {
        try { App.bridge.start_run(); } catch {}
      }
      // Also try runStartBtn
      const rs = document.getElementById('runStartBtn');
      if (rs) rs.click();
    });
    const closeCfg = document.getElementById('closeBlockConfigBtn');
    if (closeCfg) closeCfg.addEventListener('click', () => this.deselect());
  },

  bindBridgeSignals() {
    if (!App.bridge) return;
    try {
      if (App.bridge.action_blocks_updated) App.bridge.action_blocks_updated.connect((p) => this.onBlocksUpdated(p));
      if (App.bridge.job_action_status) App.bridge.job_action_status.connect((jobId, blockId, statusJson) => this.onJobActionStatus(jobId, blockId, statusJson));
      if (App.bridge.job_started) App.bridge.job_started.connect((jobId, imagePath) => this.onJobStarted(jobId, imagePath));
      if (App.bridge.job_finished) App.bridge.job_finished.connect((jobId, resultJson) => this.onJobFinished(jobId, resultJson));
      // If backend has pause signals
      if (App.bridge.run_paused) App.bridge.run_paused.connect((reason) => this.setPaused(true, reason));
      if (App.bridge.run_resumed) App.bridge.run_resumed.connect(() => this.setPaused(false, ''));
      if (App.bridge.captcha_detected) App.bridge.captcha_detected.connect((msg) => this.setPaused(true, msg || 'Security Verification / Captcha detected'));
    } catch (e) { console.warn('ActionBlocks bind signals failed', e); }
  },

  loadBuiltin() {
    if (App.bridge && App.bridge.get_builtin_blocks) {
      try {
        const res = App.bridge.get_builtin_blocks();
        if (typeof res === 'string') {
          const data = JSON.parse(res);
          if (Array.isArray(data)) this.builtinCatalog = data;
        } else if (App.bridge.get_builtin_blocks.length === 0) {
          App.bridge.get_builtin_blocks((r) => {
            try { const d = JSON.parse(r); if (Array.isArray(d)) { this.builtinCatalog = d; this.renderAddMenu(); } } catch {}
          });
        }
      } catch (e) { console.warn('loadBuiltin failed', e); }
    }
    if (!this.builtinCatalog.length) {
      this.builtinCatalog = this.getDefaultBlocks().map(b => ({
        block_id: b.block_id, name: b.name, icon: b.icon, description: b.description || '', category: b.category, required: !!b.required,
        allow_duplicate: ['CUSTOM_FIND','PAUSE','HIGHLIGHT','AWAIT_PROCESSING_IMAGE'].includes(b.block_id),
        defaults: { selector: b.selector||'', label_selector: b.label_selector||'', match_text: b.match_text||'', match_mode: b.match_mode||'contains', click_enabled: b.click_enabled!==false, click_selector: b.click_selector||'', fallback_selector: b.fallback_selector||'', fallback_text: b.fallback_text||'', highlight_enabled: b.highlight_enabled!==false, color: b.color||'#FF0000', timeout_ms: b.timeout_ms||10000, pre_delay_ms: b.pre_delay_ms||200, highlight_ms: b.highlight_ms||2000, confirm_pause_ms: b.confirm_pause_ms||700, enabled: b.enabled!==false },
        labels: {},
      }));
    }
  },

  loadCustom() {
    if (App.bridge && App.bridge.get_custom_blocks) {
      try {
        const res = App.bridge.get_custom_blocks();
        if (typeof res === 'string') { const data = JSON.parse(res); if (Array.isArray(data)) { this.customBlocks = data; this.renderCustomChips(); } }
      } catch {}
    }
  },

  load() {
    if (App.bridge && App.bridge.get_action_blocks) {
      try {
        const res = App.bridge.get_action_blocks();
        if (typeof res === 'string' && res.trim()) {
          try {
            const data = JSON.parse(res);
            if (Array.isArray(data) && data.length>0) { this.blocks=data; this.render(); return; }
          } catch (e) { console.warn('parse action blocks failed', e); }
        }
        if (typeof App.bridge.get_action_blocks === 'function') {
          try {
            App.bridge.get_action_blocks((r) => {
              try {
                const d = typeof r === 'string' ? JSON.parse(r) : r;
                if (Array.isArray(d) && d.length>0) this.blocks=d; else { this.blocks=this.getDefaultBlocks(); }
                this.render();
              } catch (e) { this.blocks=this.getDefaultBlocks(); this.render(); }
            });
            return;
          } catch (e) {}
        }
      } catch (e) {}
    }
    this.blocks = this.getDefaultBlocks();
    this.render();
  },

  getDefaultBlocks() {
    // Updated to match target screenshot: Highlight Attach, Observe Baseline, Check Security Verification Dialog (captcha), Wait for Image to Finish Generating (await_result)
    const defs = {
      CUSTOM_FIND: {name: 'Find & Click', icon: 'search', color: '#ff2d2d', category: 'action', description: 'Generic visual click'},
      OBSERVE_BASELINE: {name: 'Observe Baseline', icon: 'visibility', color: '#5AA9FF', category: 'observe', required: true},
      CHECK_SECURITY: {name: 'Check Security Verification Dialog', icon: 'captcha', color: '#FF6B6B', category: 'security', description: 'Detect CAPTCHA / security verification, pause for manual solve'},
      HIGHLIGHT_ATTACH: {name: 'Highlight Attach Input', icon: 'highlight', color: '#4ADE80', category: 'visual'},
      ATTACH_IMAGE: {name: 'Attach Image', icon: 'attach_file', color: '#00FF00', category: 'action', required: true},
      VERIFY_ATTACHMENT: {name: 'Verify Attachment', icon: 'fact_check', color: '#00FF00', category: 'verify'},
      HIGHLIGHT_PROMPT: {name: 'Highlight Prompt', icon: 'highlight', color: '#00AAFF', category: 'visual'},
      INSERT_PROMPT: {name: 'Insert Prompt', icon: 'edit', color: '#00AAFF', category: 'action', required: true},
      VERIFY_PROMPT: {name: 'Verify Prompt', icon: 'verified', color: '#00AAFF', category: 'verify'},
      HIGHLIGHT_SUBMIT: {name: 'Highlight Submit', icon: 'highlight', color: '#FFAA00', category: 'visual'},
      SUBMIT: {name: 'Submit Once', icon: 'send', color: '#FFAA00', category: 'action', required: true},
      WAIT_OUTPUT: {name: 'Wait New Output', icon: 'hourglass_top', color: '#00c853', category: 'wait', required: true},
      AWAIT_PROCESSING_IMAGE: {name: 'Wait for Image to Finish Generating', icon: 'await_result', color: '#FFAA00', category: 'process', description: 'Waiting block when system detects awaiting elements e.g. processing image, awaiting API result'},
      DOWNLOAD: {name: 'Download HQ', icon: 'download', color: '#00FFAA', category: 'action', required: true},
      VALIDATE: {name: 'Validate Image', icon: 'verified', color: '#00FFAA', category: 'verify', required: true},
      SAVE: {name: 'Save *_AI.ext', icon: 'save', color: '#4ADE80', category: 'persist', required: true},
      ADVANCE: {name: 'Advance & Persist', icon: 'check_circle', color: '#4ADE80', category: 'persist', required: true},
      PAUSE: {name: 'Custom Pause', icon: 'pause', color: '#888888', category: 'control'},
      HIGHLIGHT: {name: 'Highlight Only', icon: 'center_focus_strong', color: '#00c853', category: 'visual'},
    };
    // Order matching target: 4 steps example, but default full stack includes waiting
    const order = ['HIGHLIGHT_ATTACH','OBSERVE_BASELINE','CHECK_SECURITY','AWAIT_PROCESSING_IMAGE','ATTACH_IMAGE','VERIFY_ATTACHMENT','HIGHLIGHT_PROMPT','INSERT_PROMPT','VERIFY_PROMPT','HIGHLIGHT_SUBMIT','SUBMIT','WAIT_OUTPUT','DOWNLOAD','VALIDATE','SAVE','ADVANCE'];
    return order.map((bt, idx) => ({
      id: `${bt.toLowerCase()}_${idx}`, block_id: bt, name: defs[bt]?.name || bt, description: defs[bt]?.description||'', icon: defs[bt]?.icon || 'extension', color: defs[bt]?.color || '#888', category: defs[bt]?.category || 'action', required: !!defs[bt]?.required, enabled: true,
      selector: '', label_selector: '', match_text: '', match_mode: 'contains', click_enabled: true, click_selector: '', fallback_selector: '', fallback_text: '', highlight_enabled: true,
      timeout_ms: (defs[bt]?.category==='wait' || defs[bt]?.category==='process')?180000:10000, highlight_ms:2000, highlight_duration_ms:2000, pre_delay_ms:200, confirm_pause_ms:700, custom_name:'', extra:{},
    }));
  },

  onBlocksUpdated(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      if (Array.isArray(data)) {
        this.blocks = data.length===0 ? this.getDefaultBlocks() : data;
        this.render();
        if (typeof LogConsole !== 'undefined') LogConsole.log(`📦 Action blocks updated: ${this.blocks.length} blocks`, 'info');
      }
    } catch (e) { console.warn('onBlocksUpdated parse failed', e); }
  },

  onJobStarted(jobId, imagePath) {
    this.currentJobId = jobId;
    if (!this.jobStatuses[jobId]) { this.jobStatuses[jobId]={}; this.jobOrder.push(jobId); if (this.jobOrder.length>20){ const old=this.jobOrder.shift(); delete this.jobStatuses[old]; } }
    this.setPaused(false, '');
    if (typeof LogConsole !== 'undefined') LogConsole.log(`🚀 Job started [${jobId.slice(0,8)}] ${imagePath}`, 'success');
    this.renderJobStack(jobId); this.renderAllJobs(); this.updateFooter();
  },

  onJobActionStatus(jobId, blockId, statusJson) {
    try {
      const status = typeof statusJson === 'string' ? JSON.parse(statusJson) : statusJson;
      if (!this.jobStatuses[jobId]) { this.jobStatuses[jobId]={}; if (!this.jobOrder.includes(jobId)) this.jobOrder.push(jobId); }
      this.jobStatuses[jobId][blockId]=status;
      this.currentJobId=jobId;

      // Detect waiting / captcha pause
      const blockName = (status.block_name || blockId || '').toLowerCase();
      const msg = (status.message || '').toLowerCase();
      const isCaptcha = blockName.includes('security') || blockName.includes('captcha') || msg.includes('captcha') || msg.includes('security verification') || msg.includes('verification dialog') || status.block_id==='CHECK_SECURITY';
      const isAwaiting = blockName.includes('await') || blockName.includes('processing') || msg.includes('processing') || msg.includes('awaiting') || status.status==='waiting';

      if (isCaptcha && (status.status==='running' || status.status==='waiting' || status.status==='paused')) {
        this.setPaused(true, status.message || 'Security Verification / Captcha detected — solve manually, then resume');
      } else if (status.status==='waiting' && isAwaiting) {
        // Show waiting but not full pause
        const statusEl = document.getElementById('abStatus');
        if (statusEl) statusEl.textContent = `Status: Waiting — ${status.block_name || 'processing image'}`;
      }

      if (status.status==='success' && isCaptcha) {
        // Captcha solved, resume
        this.setPaused(false, '');
      }

      const level = status.status==='failed'?'error':status.status==='success'?'success':'info';
      if (typeof LogConsole !== 'undefined') LogConsole.log(`[${jobId.slice(0,8)}] ${status.block_name||blockId}: ${status.status} ${status.message||''}`, level);
      if (status.rect && typeof HighlightOverlay !== 'undefined') {
        HighlightOverlay.show({ x: status.rect.x||0, y: status.rect.y||0, width: status.rect.width||100, height: status.rect.height||100, duration: (status.highlight_duration_ms||status.highlight_ms||2000)/1000, label: status.block_name||blockId, color: status.color||'#FF0000' });
      }
      this.renderJobStack(jobId); this.renderAllJobs(); this.updateFooter();
    } catch (e) { console.warn('onJobActionStatus parse failed', e, statusJson); }
  },

  onJobFinished(jobId, resultJson) {
    try {
      const result = typeof resultJson === 'string' ? JSON.parse(resultJson) : resultJson;
      const level = result.status==='completed'?'success':'error';
      if (typeof LogConsole !== 'undefined') LogConsole.log(`🏁 Job [${jobId.slice(0,8)}] finished: ${result.status} ${result.message||''}`, level);
      this.setPaused(false, '');
      this.renderJobStack(jobId); this.renderAllJobs(); this.updateFooter();
    } catch (e) {}
  },

  updateFooter() {
    const totalEl = document.getElementById('abTotalSteps');
    const selEl = document.getElementById('abSelectedSteps');
    const statusEl = document.getElementById('abStatus');
    if (totalEl) totalEl.textContent = `Total: ${this.blocks.length} steps`;
    if (selEl) {
      const enabledCount = this.blocks.filter(b=>b.enabled!==false).length;
      selEl.textContent = `Selected: ${enabledCount} steps`;
    }
    if (statusEl && !this._isPaused) {
      if (this.currentJobId) {
        const statuses = this.jobStatuses[this.currentJobId] || {};
        const running = Object.values(statuses).find(s=>s.status==='running');
        if (running) statusEl.textContent = `Status: Running — ${running.block_name || running.block_id}`;
        else statusEl.textContent = 'Status: Awaiting run command';
      } else {
        statusEl.textContent = 'Status: Awaiting run command';
      }
    }
    const countEl = document.getElementById('actionBlocksCount');
    if (countEl) countEl.textContent = `${this.blocks.length} blocks`;
  },

  render() {
    const container = document.getElementById('actionBlocksStack');
    if (!container) return;
    container.innerHTML='';
    if (!this.blocks || this.blocks.length===0) { this.blocks=this.getDefaultBlocks(); }
    this.blocks.forEach((block, idx) => {
      try { container.appendChild(this.createBlockElement(block, idx)); } catch(e){ console.error('Failed to create block element', block, e); }
    });
    this.renderAddMenu(); this.renderCustomChips();
    this.updateFooter();
    if (this.selectedIdx>=0 && this.selectedIdx<this.blocks.length) this.showConfig(this.selectedIdx); else this.showConfig(null);
    if (this.currentJobId){ this.renderJobStack(this.currentJobId); this.renderAllJobs(); }
    if (!this.currentJobId){ this.renderAllJobs(); }
  },

  badgeClassForBlock(block) {
    const icon = (block.icon || '').toLowerCase();
    const bid = (block.block_id || '').toLowerCase();
    const cat = (block.category || '').toLowerCase();
    if (icon.includes('highlight') || bid.includes('highlight')) return 'ab-badge-highlight';
    if (icon.includes('visibility') || cat==='observe') return 'ab-badge-visibility';
    if (icon.includes('captcha') || icon.includes('security') || bid.includes('security') || bid==='check_security') return 'ab-badge-captcha';
    if (icon.includes('await') || bid.includes('await') || cat==='process' || cat==='wait') return 'ab-badge-await_result';
    if (cat==='action' || icon==='search') return 'ab-badge-action';
    return '';
  },

  createBlockElement(block, idx) {
    const div=document.createElement('div');
    div.className='action-block';
    if (idx===this.selectedIdx) div.classList.add('selected');
    div.draggable=true;
    div.dataset.blockId=block.id;
    div.dataset.index=idx;
    const isRequired=!!block.required;
    const enabled=block.enabled!==false;
    div.style.setProperty('--block-color', block.color || '#888');
    div.style.opacity = enabled ? '1' : '0.55';

    // Drag handle — ≡ reorder icon
    const dragHandle=document.createElement('span');
    dragHandle.className='material-icons ab-drag-handle';
    dragHandle.textContent='reorder';
    dragHandle.title='Drag to reorder — alt+↑↓ also works';
    dragHandle.draggable=false;

    // Badge pill — icon name as text like target: highlight, visibility, captcha, await_result
    const badge=document.createElement('span');
    const badgeCls = this.badgeClassForBlock(block);
    badge.className=`ab-badge ${badgeCls}`;
    const badgeText = block.icon || block.category || 'action';
    badge.textContent = badgeText;
    badge.title = `${block.block_id} icon: ${badgeText}`;

    // Info
    const info=document.createElement('div');
    info.className='ab-block-info';
    const title=document.createElement('div');
    title.className='ab-block-title';
    title.textContent = block.custom_name || block.name;
    title.title = block.description || block.name;
    const meta=document.createElement('div');
    meta.className='ab-block-meta';
    const selPreview = block.selector ? block.selector.slice(0,40) : '';
    const extra = block.match_text ? ` • "${block.match_text.slice(0,18)}"` : '';
    meta.textContent = `${block.block_id} • ${block.category}${selPreview?' • '+selPreview:''}${extra}`;
    info.appendChild(title);
    info.appendChild(meta);
    info.addEventListener('click', ()=>this.selectBlock(idx));

    // Controls
    const controls=document.createElement('div');
    controls.className='ab-block-controls';
    const check=document.createElement('input');
    check.type='checkbox';
    check.className='ab-check';
    check.checked=enabled;
    check.disabled=isRequired;
    check.title=isRequired?'Required block cannot be disabled':'Enable/disable — alt+click for quick toggle';
    check.addEventListener('change',(e)=>{ e.stopPropagation(); this.toggleBlock(block.id, check.checked); });
    check.addEventListener('click',(e)=>e.stopPropagation());

    const editBtn=document.createElement('button');
    editBtn.className='ab-edit-btn';
    editBtn.innerHTML='<span class="material-icons">edit</span> edit';
    editBtn.title='Edit block';
    editBtn.addEventListener('click',(e)=>{ e.stopPropagation(); this.selectBlock(idx); });

    const delBtn=document.createElement('button');
    delBtn.className='ab-delete-btn';
    delBtn.innerHTML='<span class="material-icons">delete</span> delete';
    delBtn.title=isRequired?'Required block cannot be deleted':'Delete block';
    delBtn.disabled=isRequired;
    if (isRequired) delBtn.style.opacity='0.35';
    delBtn.addEventListener('click',(e)=>{ e.stopPropagation(); this.deleteBlock(block.id); });

    controls.appendChild(check);
    controls.appendChild(editBtn);
    controls.appendChild(delBtn);

    div.appendChild(dragHandle);
    div.appendChild(badge);
    div.appendChild(info);
    div.appendChild(controls);

    // Drag & drop with animation
    div.addEventListener('dragstart',(e)=>{
      this._dragSrc=div;
      e.dataTransfer.effectAllowed='move';
      e.dataTransfer.setData('text/plain', block.id);
      requestAnimationFrame(()=>div.classList.add('dragging'));
    });
    div.addEventListener('dragend',()=>{
      div.classList.remove('dragging');
      this._dragSrc=null;
      const cont=document.getElementById('actionBlocksStack');
      if (cont) cont.querySelectorAll('.action-block').forEach(el=>{ el.classList.remove('drag-over'); });
    });
    div.addEventListener('dragover',(e)=>{
      e.preventDefault();
      e.dataTransfer.dropEffect='move';
      if (this._dragSrc && this._dragSrc!==div) {
        div.classList.add('drag-over');
      }
    });
    div.addEventListener('dragleave',()=>{
      div.classList.remove('drag-over');
    });
    div.addEventListener('drop',(e)=>{
      e.preventDefault();
      div.classList.remove('drag-over');
      if (this._dragSrc && this._dragSrc!==div){
        const srcIdx=parseInt(this._dragSrc.dataset.index);
        const dstIdx=parseInt(div.dataset.index);
        if (!isNaN(srcIdx)&&!isNaN(dstIdx)) this.moveBlock(srcIdx,dstIdx);
      }
    });

    // Double-click to highlight
    if (block.selector){
      div.addEventListener('dblclick',()=>{
        if (App.bridge&&App.bridge.highlight_selector){
          App.bridge.highlight_selector(block.selector, block.color, block.highlight_ms||block.highlight_duration_ms||2000, block.display_name||block.name);
          if (typeof LogConsole!=='undefined') LogConsole.log(`🔍 Highlighting ${block.selector}`, 'info');
        }
      });
      div.title=`Double-click to highlight: ${block.selector} — Click to configure — Alt+↑↓ to reorder`;
    } else {
      div.title='Click to configure — Alt+↑↓ to reorder';
    }

    return div;
  },

  selectBlock(idx) {
    if (idx===null||idx<0||idx>=this.blocks.length){ this.selectedIdx=-1; this.showConfig(null); this.render(); return; }
    this.selectedIdx=idx; this.render(); this.showConfig(idx);
    try {
      if (window.SashGrid && SashGrid.showWindow) SashGrid.showWindow('block_config');
      else if (window.ArenaApp && ArenaApp.sash && ArenaApp.sash.showWindow) ArenaApp.sash.showWindow('block_config');
    } catch {}
  },

  deselect(){ this.selectedIdx=-1; this.showConfig(null); this.render(); },

  showConfig(idx) {
    const formContainer=document.getElementById('blockConfigForm');
    const headContainer=document.getElementById('blockConfigHead');
    if(!formContainer) return;
    if(idx===null||idx===undefined){
      if(headContainer) headContainer.innerHTML='<div class="bc-head-empty"><span class="material-icons" style="font-size:16px; vertical-align:middle;">tune</span> Select a block to configure — all params storable in preset JSON, rect duration configurable</div>';
      formContainer.innerHTML=`
        <div class="block-config-win empty">
          <div style="padding:16px; color:var(--text-muted); font-size:11px; line-height:1.6;">
            <p><b style="color:var(--text-primary); font-size:12px;">Action Blocks</b> — stacking jobs system restored from Old App.</p>
            <p>Each block is a separate job: click on btn, click on text areas, visual confirmations seeing images/waiting.</p>
            <div style="display:grid; grid-template-columns:auto 1fr; gap:4px 10px; margin:10px 0; font-size:11px;">
              <span style="color:#ff2d2d">⬤</span><span>RED outline = found element</span>
              <span style="color:#ff9500">⬤</span><span>ORANGE = click target</span>
              <span style="color:#00c853">⬤</span><span>GREEN = new output / match</span>
              <span style="color:#00AAFF">⬤</span><span>BLUE = prompt</span>
              <span style="color:#FFAA00">⬤</span><span>YELLOW = submit</span>
            </div>
            <p><b>Reorder:</b> Drag handle ≡ or Alt+↑/↓ — all params stored in preset JSON.</p>
            <p>Double-click block row to highlight its selector on page for N seconds (saved in preset JSON).</p>
          </div>
        </div>`;
      return;
    }
    const block=this.blocks[idx];
    if(!block){ formContainer.innerHTML=''; return; }
    const meta=this.builtinCatalog.find(b=>b.block_id===block.block_id)||{labels:{}, defaults:{}};
    const labels=meta.labels||{};

    if(headContainer){
      const safeName=this.esc(block.custom_name||block.name||block.block_id);
      const cat=(block.category||'observe').toLowerCase();
      const badgeId=this.esc(block.block_id);
      const badgeCat=this.esc(cat);
      headContainer.innerHTML=`
        <div class="bc-title-row">
          <span class="material-icons bc-title-icon" style="color:${block.color||'#FF6B6B'}">${block.icon||'security'}</span>
          <span class="bc-title-text">${safeName}</span>
          <span class="bc-badge bc-badge-id">${badgeId}</span>
          <span class="bc-badge bc-badge-cat">${badgeCat}</span>
          <span class="spacer"></span>
          <button class="btn-small bc-close-btn" onclick="ActionBlocksPanel.deselect()" title="Close"><span class="material-icons" style="font-size:14px;">close</span></button>
        </div>`;
    }

    let fields;
    if(block.block_id==='CHECK_SECURITY'){
      fields=[
        {key:'custom_name', type:'text', label:'Block name (shown in stack & logs)', placeholder:'Check Security Verification Dialog'},
        {key:'selector', type:'text', label:'Security dialog selector (CSS)', placeholder:'div[role="dialog"], iframe[title*="reCAPTCHA"]'},
        {key:'click_enabled', type:'checkbox', label:'Click after found (if needed)'},
        {key:'highlight_enabled', type:'checkbox', label:'Visual confirmation — pause corner overlay'},
        {key:'color', type:'color', label:'Highlight color (hex)', placeholder:'#FF6B6B'},
        {key:'pre_delay_ms', type:'number', label:'Pre-delay (ms)', min:0, max:10000, step:50},
        {key:'confirm_pause_ms', type:'number', label:'Pause after found to eyeball red outline (ms)', min:0, max:5000, step:100},
        {key:'highlight_ms', type:'number', label:'Highlight duration (ms)', min:100, max:10000, step:100},
        {key:'timeout_ms', type:'number', label:'Timeout (ms) — after timeout, show ON PAUSE', min:1000, max:300000, step:1000},
        {key:'enabled', type:'checkbox', label:'Enabled'},
      ];
    } else if(block.block_id==='AWAIT_PROCESSING_IMAGE' || block.block_id==='WAIT_OUTPUT'){
      fields=[
        {key:'custom_name', type:'text', label:'Block name', placeholder: block.block_id==='AWAIT_PROCESSING_IMAGE'?'Wait for Image to Finish Generating':'Wait New Output'},
        {key:'selector', type:'text', label:'Output image selector (CSS) — detects new image', placeholder:'div.no-scrollbar img, img.aspect-square'},
        {key:'highlight_enabled', type:'checkbox', label:'Visual confirmation — GREEN collect on new output'},
        {key:'color', type:'color', label:'Highlight color (hex)', placeholder:'#00c853'},
        {key:'pre_delay_ms', type:'number', label:'Pre-delay (ms)', min:0, max:5000, step:100},
        {key:'highlight_ms', type:'number', label:'Highlight duration (ms)', min:500, max:10000, step:100},
        {key:'timeout_ms', type:'number', label:'Timeout (ms) — waiting for image / API result', min:5000, max:600000, step:1000},
        {key:'enabled', type:'checkbox', label:'Enabled'},
      ];
    } else {
      fields=[
        {key:'custom_name', type:'text', label: labels.custom_name||'Block name (shown in stack & logs)', placeholder:'Custom name'},
        {key:'selector', type:'text', label: labels.selector||'Element to find — clickable box (CSS)', placeholder:'e.g. button[aria-label="Add files"]'},
        {key:'label_selector', type:'text', label: labels.label_selector||'Inner text element inside it (CSS, optional)', placeholder:'e.g. span, .primary-text'},
        {key:'match_text', type:'text', label: labels.match_text||'Text it must contain (empty=first)', placeholder:'e.g. Add files'},
        {key:'match_mode', type:'select', label:'Match mode', options:['contains','exact']},
        {key:'click_enabled', type:'checkbox', label: labels.click_enabled||'Click after found'},
        {key:'click_selector', type:'text', label: labels.click_selector||'Or click inner element instead (CSS, optional)', placeholder:'e.g. button, input'},
        {key:'fallback_selector', type:'text', label:'Fallback selector (CSS, optional)', placeholder:'Fallback if first fails'},
        {key:'fallback_text', type:'text', label:'Fallback text', placeholder:'Fallback icon text'},
        {key:'highlight_enabled', type:'checkbox', label: labels.highlight_enabled||'Visual confirmation'},
        {key:'color', type:'color', label: labels.color||'Highlight color (hex)', placeholder:'#ff2d2d'},
        {key:'pre_delay_ms', type:'number', label: labels.pre_delay_ms||'Pre-delay (ms)', min:0, max:10000, step:100},
        {key:'confirm_pause_ms', type:'number', label: labels.confirm_pause_ms||'Pause after found to eyeball red outline (ms)', min:0, max:5000, step:100},
        {key:'highlight_ms', type:'number', label: labels.highlight_ms||'How long outline stays visible (ms) — saved in preset JSON', min:100, max:10000, step:100},
        {key:'timeout_ms', type:'number', label: labels.timeout_ms||'Timeout (ms)', min:1000, max:300000, step:1000},
        {key:'enabled', type:'checkbox', label:'Enabled (on/off toggle)'},
      ];
      if(['OBSERVE_BASELINE','HIGHLIGHT_ATTACH','HIGHLIGHT_PROMPT','HIGHLIGHT_SUBMIT','HIGHLIGHT','VERIFY_ATTACHMENT','VERIFY_PROMPT','DOWNLOAD','VALIDATE','SAVE','ADVANCE','PAUSE'].includes(block.block_id)){
        const hide=block.block_id==='HIGHLIGHT'?['click_selector','fallback_selector','fallback_text']: block.block_id==='PAUSE'?['selector','label_selector','match_text','match_mode','click_enabled','click_selector','fallback_selector','fallback_text','highlight_enabled','color','confirm_pause_ms','highlight_ms']: ['label_selector','match_text','match_mode','click_selector','fallback_selector','fallback_text'];
        if(block.block_id==='PAUSE'){ fields=fields.filter(f=>['custom_name','timeout_ms','enabled'].includes(f.key)||f.key==='pre_delay_ms'); fields.unshift({key:'duration_ms', type:'number', label:'Duration (ms)', min:100, max:60000, step:100}); } else { fields=fields.filter(f=>!hide.includes(f.key)); }
      }
    }

    let html=`<div class="block-config-win"><div class="bc-card">`;
    if(block.block_id==='CUSTOM_FIND'){ html+=`<div class="bc-hint">Configurable search-and-click constructor: field ① finds the clickable element (box/rectangle); field ② is separate inner text to confirm. Visual confirmation RED→pause→ORANGE. Save as preset for reuse. Alt+↑↓ to reorder.</div>`; }
    if(block.block_id==='CHECK_SECURITY'){ html+=`<div class="bc-hint">Captcha detected → app pauses → display "on pause" state clearly. Visualize pause state in webpage corner — unmistakable. Never bypass, let user solve manually. Rect saved in preset JSON.</div>`; }
    if(block.block_id==='AWAIT_PROCESSING_IMAGE'){ html+=`<div class="bc-hint">Waiting block when system detects awaiting elements e.g. processing image, awaiting API result. Shows waiting state, not error. All params stored in preset JSON.</div>`; }

    fields.forEach(f=>{
      const val=block[f.key]!==undefined?block[f.key]:(f.type==='checkbox'?false:'');
      const disabledAttr=(f.key==='enabled'&&block.required)?'disabled':'';
      if(f.type==='checkbox'){
        html+=`<div class="bc-row bc-row-check"><label class="bc-label">${this.esc(f.label)}</label><div class="bc-control"><input data-key="${f.key}" type="checkbox" ${val?'checked':''} ${disabledAttr} class="bc-checkbox"></div></div>`;
      } else if(f.type==='select'){
        const opts=f.options.map(o=>`<option value="${o}" ${String(val)===String(o)?'selected':''}>${o}</option>`).join('');
        html+=`<div class="bc-row"><label class="bc-label">${this.esc(f.label)}</label><div class="bc-control"><select data-key="${f.key}" class="bc-input bc-select">${opts}</select></div></div>`;
      } else if(f.type==='color'){
        const safeVal=this.esc(String(val||f.placeholder||'#FF6B6B'));
        let hexVal=String(val||'').trim(); if(!/^#[0-9a-fA-F]{6}$/.test(hexVal)) hexVal=f.placeholder||'#FF6B6B';
        if(!/^#[0-9a-fA-F]{6}$/.test(hexVal)) hexVal='#FF6B6B';
        html+=`<div class="bc-row"><label class="bc-label">${this.esc(f.label)}</label><div class="bc-control bc-control-color"><span class="bc-color-preview" style="background:${hexVal};"></span><input data-key="${f.key}" value="${safeVal}" type="text" placeholder="${this.esc(f.placeholder||'')}" class="bc-input bc-input-color"><input data-key="${f.key}_picker" type="color" value="${hexVal}" class="bc-color-picker"></div></div>`;
      } else {
        const inputType=f.type==='number'?'number':'text';
        const extra=f.type==='number'?`min="${f.min||0}" max="${f.max||100000}" step="${f.step||1}"`:`placeholder="${this.esc(f.placeholder||'')}"`;
        const safeVal=f.type==='text'?String(val||'').replace(/\"/g,'&quot;'):(val||0);
        html+=`<div class="bc-row"><label class="bc-label">${this.esc(f.label)}</label><div class="bc-control"><input data-key="${f.key}" value="${safeVal}" type="${inputType}" ${extra} class="bc-input"></div></div>`;
      }
    });

    if(block.extra && Object.keys(block.extra).length>0){
      html+=`<div class="bc-row bc-row-full"><label class="bc-label">Extra (JSON)</label><div class="bc-control"><textarea data-key="_extra_json" rows="2" class="bc-input bc-textarea">${this.esc(JSON.stringify(block.extra))}</textarea></div></div>`;
    }
    if(block.block_id==='CUSTOM_FIND'){
      html+=`<div class="bc-row bc-row-full" style="margin-top:8px;"><button id="saveCustomBlockBtnInline" class="btn-small btn-primary" style="width:100%;"><span class="material-icons" style="font-size:14px; vertical-align:middle;">bookmark_add</span> Save as Custom Preset</button></div>`;
    }
    html+=`</div></div>`;
    formContainer.innerHTML=html;

    formContainer.querySelectorAll('input[data-key], select[data-key], textarea[data-key]').forEach(inp=>{
      const k=inp.dataset.key;
      if(k==='_extra_json') return;
      if(k.endsWith('_picker')){
        const base=k.replace('_picker','');
        inp.addEventListener('input', ()=>{
          const textInput=formContainer.querySelector(`input[data-key="${base}"][type="text"]`);
          const preview=formContainer.querySelector('.bc-color-preview');
          if(textInput) textInput.value=inp.value.toUpperCase();
          if(preview) preview.style.background=inp.value;
          block[base]=inp.value.toUpperCase();
          this.saveDebounced();
        });
        return;
      }
      const handler=()=>{
        if(inp.type==='checkbox'){ block[k]=inp.checked; }
        else if(inp.type==='number'){ const num=Number(inp.value); if(k==='duration_ms'){ if(!block.extra) block.extra={}; block.extra.duration_ms=num; } else block[k]=num; }
        else {
          block[k]=inp.value;
          if(k==='color'){
            const picker=formContainer.querySelector(`input[data-key="${k}_picker"]`);
            const preview=formContainer.querySelector('.bc-color-preview');
            const v=inp.value.trim();
            if(/^#[0-9a-fA-F]{6}$/.test(v)){ if(picker) picker.value=v; if(preview) preview.style.background=v; }
          }
        }
        if(k==='highlight_ms') block.highlight_duration_ms=block.highlight_ms;
        if(k==='custom_name'||k==='selector'||k==='enabled') this.render();
        this.saveDebounced();
      };
      inp.addEventListener('change', handler);
      if(inp.type==='text'){ inp.addEventListener('input', ()=>{ if(k==='custom_name'){ block[k]=inp.value; const row=document.querySelector(`.action-block[data-block-id="${block.id}"] .ab-block-title`); if(row) row.textContent=inp.value||block.name; } }); }
    });
    const extraTa=formContainer.querySelector('textarea[data-key="_extra_json"]');
    if(extraTa){ extraTa.addEventListener('change', ()=>{ try{ block.extra=JSON.parse(extraTa.value); this.saveDebounced(); } catch(e){ if(typeof LogConsole!=='undefined') LogConsole.log(`Extra JSON parse failed: ${e}`, 'error'); } }); }
    const inlineSave=document.getElementById('saveCustomBlockBtnInline');
    if(inlineSave){ inlineSave.addEventListener('click', ()=>this.saveBlockAsCustom(block)); }
  },

  esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;'); },

  _saveTimer:null,
  saveDebounced(){ clearTimeout(this._saveTimer); this._saveTimer=setTimeout(()=>this.save(),600); try{ if(App.bridge&&App.bridge.push_global_history){ const payload=JSON.stringify(this.blocks); App.bridge.push_global_history('action_blocks', payload); } } catch{} },

  moveBlock(fromIdx,toIdx){ if(fromIdx===toIdx) return; const block=this.blocks.splice(fromIdx,1)[0]; this.blocks.splice(toIdx,0,block); this.selectedIdx=toIdx; this.save(); this.render(); if(typeof LogConsole!=='undefined') LogConsole.log(`↕ Moved block ${block.name} from ${fromIdx} to ${toIdx} — alt+↑↓ works too`, 'info'); },
  toggleBlock(blockId,enabled){ const b=this.blocks.find(x=>x.id===blockId); if(!b) return; if(b.required&&!enabled){ if(typeof LogConsole!=='undefined') LogConsole.log(`⚠ Cannot disable required block ${b.name}`, 'warn'); return; } b.enabled=enabled; this.save(); this.render(); if(typeof LogConsole!=='undefined') LogConsole.log(`${enabled?'✅ Enabled':'⏸ Disabled'} ${b.name}`, enabled?'success':'warn'); },
  deleteBlock(blockId){ const idx=this.blocks.findIndex(b=>b.id===blockId); if(idx===-1) return; const block=this.blocks[idx]; if(block.required){ if(typeof LogConsole!=='undefined') LogConsole.log(`⚠ Cannot delete required block ${block.name}`, 'warn'); return; } if(!confirm(`Delete block ${block.custom_name||block.name}?`)) return; this.blocks.splice(idx,1); if(this.selectedIdx===idx) this.selectedIdx=-1; else if(this.selectedIdx>idx) this.selectedIdx--; this.save(); this.render(); if(typeof LogConsole!=='undefined') LogConsole.log(`🗑 Deleted block ${block.name}`, 'warn'); },

  showAddDialog(){
    const existingTypes=new Set(this.blocks.map(b=>b.block_id));
    const available=this.builtinCatalog.length?this.builtinCatalog:this.getDefaultBlocks().map(b=>({block_id:b.block_id, name:b.name, required:!!b.required, allow_duplicate:b.block_id==='CUSTOM_FIND'||b.block_id==='PAUSE'||b.block_id==='HIGHLIGHT'||b.block_id==='AWAIT_PROCESSING_IMAGE'}));
    const choices=available.filter(bt=>{ if(bt.allow_duplicate) return true; return !existingTypes.has(bt.block_id); });
    if(choices.length===0){ alert('All block types already in stack. CUSTOM_FIND, PAUSE, HIGHLIGHT, AWAIT_PROCESSING_IMAGE can be duplicated via Add.'); return; }
    const listText=choices.map(c=>`${c.block_id} — ${c.name}${c.required?' (required)':''}`).join('\n');
    const bt=prompt(`Add block type:\n${listText}\n\nEnter block_id (e.g. CUSTOM_FIND or AWAIT_PROCESSING_IMAGE):`, choices[0].block_id);
    if(!bt) return; const upper=bt.trim().toUpperCase(); const found=available.find(c=>c.block_id===upper);
    if(!found){ if(typeof LogConsole!=='undefined') LogConsole.log(`⚠ Unknown block type ${bt}`, 'warn'); return; }
    if(App.bridge&&App.bridge.add_action_block){
      App.bridge.add_action_block(upper, (res)=>{ try{ const r=typeof res==='string'?JSON.parse(res):res; if(r.ok){ if(typeof LogConsole!=='undefined') LogConsole.log(`➕ Added block ${upper}`, 'success'); this.load(); } else { if(typeof LogConsole!=='undefined') LogConsole.log(`Add failed: ${r.error}`, 'error'); } } catch(e){ this.load(); } });
      try{ const res=App.bridge.add_action_block(upper); if(typeof res==='string'){ const r=JSON.parse(res); if(r.ok) this.load(); } } catch{}
    } else { const def=this.getDefaultBlocks().find(b=>b.block_id===upper); if(def){ this.blocks.push({...def, id:`${upper.toLowerCase()}_${Date.now()}`}); this.save(); this.render(); } }
  },

  resetToDefault(){
    if(!confirm('Reset action blocks to default stack? This will overwrite current stack.')) return;
    if(App.bridge&&App.bridge.reset_action_blocks){
      try{ const res=App.bridge.reset_action_blocks(); if(typeof res==='string'){ const r=JSON.parse(res); if(r.ok){ if(typeof LogConsole!=='undefined') LogConsole.log('🔄 Action blocks reset to default', 'info'); this.load(); return; } } } catch{}
      App.bridge.reset_action_blocks((res)=>{ try{ const r=typeof res==='string'?JSON.parse(res):res; if(r.ok){ if(typeof LogConsole!=='undefined') LogConsole.log('🔄 Action blocks reset to default', 'info'); this.load(); } } catch{} });
    } else { this.blocks=this.getDefaultBlocks(); this.save(); this.render(); }
  },

  save(){
    if(App.bridge&&App.bridge.save_action_blocks){
      const payload=JSON.stringify(this.blocks);
      try{ const res=App.bridge.save_action_blocks(payload); if(typeof res==='string'){ const r=JSON.parse(res); if(r.ok){ if(typeof LogConsole!=='undefined') LogConsole.log(`💾 Saved ${this.blocks.length} action blocks`, 'success'); } } } catch{}
      try{ App.bridge.save_action_blocks(payload, (res)=>{ try{ const r=typeof res==='string'?JSON.parse(res):res; if(r.ok){ if(typeof LogConsole!=='undefined') LogConsole.log(`💾 Saved ${this.blocks.length} action blocks`, 'success'); } } catch{} }); } catch{}
    }
  },

  export(){ const data=JSON.stringify(this.blocks,null,2); const blob=new Blob([data],{type:'application/json'}); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=`arena-action-blocks-${new Date().toISOString().slice(0,10)}.json`; a.click(); URL.revokeObjectURL(url); if(typeof LogConsole!=='undefined') LogConsole.log('📤 Exported action blocks', 'success'); },
  import(){ const input=document.createElement('input'); input.type='file'; input.accept='.json'; input.onchange=(e)=>{ const file=e.target.files[0]; if(!file) return; const reader=new FileReader(); reader.onload=(ev)=>{ try{ const data=JSON.parse(ev.target.result); if(Array.isArray(data)){ this.blocks=data; this.save(); this.render(); if(typeof LogConsole!=='undefined') LogConsole.log(`📥 Imported ${data.length} action blocks`, 'success'); } } catch(err){ if(typeof LogConsole!=='undefined') LogConsole.log(`Import failed: ${err}`, 'error'); } }; reader.readAsText(file); }; input.click(); },

  renderCustomChips(){
    const el=document.getElementById('customBlockChips'); if(!el) return;
    if(!this.customBlocks.length){ el.innerHTML='<span class="preset-row-empty" style="font-size:10px; color:var(--text-muted);">no saved custom Find & Click blocks — configure a CUSTOM_FIND block and press “Save as Custom Preset”</span>'; return; }
    el.innerHTML=''; this.customBlocks.forEach((c)=>{ const blk=c.block||{}; const label=blk.custom_name||c.name||'Custom block'; const chip=document.createElement('div'); chip.className='preset-chip'; chip.style.cssText='display:inline-flex; align-items:center; gap:4px; padding:6px 10px; margin:2px; background:var(--bg-input); border:1px solid var(--border); border-radius:12px; font-size:11px; cursor:pointer;'; chip.innerHTML=`<span>🔎 ${this.esc(label)}</span> <button class="btn-icon" title="Delete" style="margin-left:4px;"><span class="material-icons" style="font-size:12px;">close</span></button>`; chip.addEventListener('click',(e)=>{ if(e.target.closest('button')) return; this.addCustomBlock(c); }); const delBtn=chip.querySelector('button'); if(delBtn) delBtn.addEventListener('click',(e)=>{ e.stopPropagation(); this.deleteCustomBlock(c.name||label); }); chip.title='Add this custom Find & Click block to the stack'; el.appendChild(chip); });
  },
  addCustomBlock(entry){ if(!entry||!entry.block) return; const block=entry.block; const newBlock={...block, id:`${block.block_id.toLowerCase()}_${Date.now()}`}; this.blocks.push(newBlock); this.save(); this.render(); if(typeof LogConsole!=='undefined') LogConsole.log(`🔎 Custom block “${block.custom_name||entry.name}” added to the stack`, 'success'); },
  deleteCustomBlock(name){
    if(!App.bridge) return; if(!confirm(`Delete custom block preset "${name}"?`)) return;
    if(App.bridge.delete_custom_block){
      try{ const res=App.bridge.delete_custom_block(name); if(typeof res==='string'){ const r=JSON.parse(res); if(r.ok){ this.loadCustom(); } } } catch{}
      App.bridge.delete_custom_block(name, (res)=>{ try{ const r=typeof res==='string'?JSON.parse(res):res; if(r.ok){ this.customBlocks=this.customBlocks.filter(c=>c.name!==name); this.renderCustomChips(); } } catch{} });
    }
    this.customBlocks=this.customBlocks.filter(c=>c.name!==name); this.renderCustomChips();
  },
  saveBlockAsCustom(block){
    if(!block) return; if(block.block_id!=='CUSTOM_FIND'&&block.block_id!=='HIGHLIGHT'){ if(typeof LogConsole!=='undefined') LogConsole.log('Only CUSTOM_FIND and HIGHLIGHT blocks can be saved as custom presets', 'warn'); return; }
    const name=prompt('Save custom block as preset — enter name:', block.custom_name||block.name||'Custom Find'); if(!name) return;
    const toSave={...block, custom_name:name}; const entry={name:name, block:toSave, updated_at:new Date().toISOString()};
    if(App.bridge&&App.bridge.save_custom_block){
      const payload=JSON.stringify(entry);
      try{ const res=App.bridge.save_custom_block(payload); if(typeof res==='string'){ const r=JSON.parse(res); if(r.ok){ this.customBlocks=this.customBlocks.filter(c=>c.name!==name); this.customBlocks.push(entry); this.renderCustomChips(); } } } catch{}
      App.bridge.save_custom_block(payload, (res)=>{ try{ const r=typeof res==='string'?JSON.parse(res):res; if(r.ok) this.loadCustom(); } catch{} });
    } else { this.customBlocks=this.customBlocks.filter(c=>c.name!==name); this.customBlocks.push(entry); this.renderCustomChips(); }
  },
  saveSelectedAsCustom(){ if(this.selectedIdx<0||this.selectedIdx>=this.blocks.length){ if(typeof LogConsole!=='undefined') LogConsole.log('Select a CUSTOM_FIND block first to save as preset', 'warn'); return; } const block=this.blocks[this.selectedIdx]; this.saveBlockAsCustom(block); },
  renderAddMenu(){ const el=document.getElementById('addBlockMenu'); if(!el||!this.builtinCatalog.length) return; el.innerHTML=''; this.builtinCatalog.forEach(bt=>{ const opt=document.createElement('div'); opt.className='add-block-option'; opt.style.cssText='padding:6px 10px; cursor:pointer; font-size:11px; display:flex; gap:6px; align-items:center;'; opt.innerHTML=`<span>${bt.icon||'🔹'}</span><span>${bt.name}</span><span style="color:var(--text-muted); font-size:9px;">${bt.block_id}</span>`; opt.title=bt.description||''; opt.addEventListener('click',()=>{ if(App.bridge&&App.bridge.add_action_block){ App.bridge.add_action_block(bt.block_id); this.load(); } }); el.appendChild(opt); }); },

  renderJobStack(jobId){
    const container=document.getElementById('jobActionStack'); if(!container) return; const statuses=this.jobStatuses[jobId]||{}; container.innerHTML='';
    const title=document.createElement('div'); title.style.cssText='font-size:12px; font-weight:700; margin-bottom:6px; display:flex; justify-content:space-between; align-items:center;'; const countSuccess=Object.values(statuses).filter(s=>s.status==='success').length; title.innerHTML=`<span>Job ${jobId.slice(0,8)} — ${countSuccess}/${this.blocks.length} blocks</span><span style="color:var(--text-muted); font-weight:400; font-size:10px;">${new Date().toLocaleTimeString()}</span>`; container.appendChild(title);
    this.blocks.forEach((block)=>{ const st=statuses[block.id]||statuses[block.block_id]||{status:'pending', message:''}; const row=document.createElement('div'); const statusColor=st.status==='success'?'#4ADE80':st.status==='failed'?'#FF6B6B':st.status==='running'?'#FFAA00':st.status==='waiting'?'#5AA9FF':st.status==='skipped'?'#888':'var(--border)'; row.style.cssText=`display:flex; align-items:center; gap:6px; padding:6px 8px; margin:3px 0; background: var(--bg-input); border:1px solid ${statusColor}; border-left:3px solid ${block.color}; border-radius:6px; font-size:11px;`; const icon=document.createElement('span'); icon.className='material-icons'; icon.style.fontSize='14px'; icon.style.color=statusColor; const iconMap={pending:'hourglass_empty', running:'play_circle', success:'check_circle', failed:'error', skipped:'skip_next', waiting:'hourglass_top', paused:'pause_circle'}; icon.textContent=iconMap[st.status]||'circle'; const name=document.createElement('span'); name.textContent=block.custom_name||block.name; name.style.flex='1'; name.title=`${block.block_id}: ${st.message||''} — selector: ${block.selector}`; const statusText=document.createElement('span'); statusText.textContent=st.status; statusText.style.cssText=`font-size:10px; color:${statusColor}; text-transform:uppercase; font-weight:600;`; const controls=document.createElement('div'); controls.style.cssText='display:flex; gap:2px;'; if(st.rect){ const rectBtn=document.createElement('button'); rectBtn.className='btn-small'; rectBtn.innerHTML='<span class="material-icons" style="font-size:12px;">highlight</span>'; rectBtn.title=`Show rect`; rectBtn.addEventListener('click',()=>{ if(typeof HighlightOverlay!=='undefined'){ HighlightOverlay.show({ x:st.rect.x, y:st.rect.y, width:st.rect.width, height:st.rect.height, duration:(st.highlight_duration_ms||2000)/1000, label:block.custom_name||block.name, color:block.color }); } }); controls.appendChild(rectBtn); } row.appendChild(icon); row.appendChild(name); row.appendChild(controls); row.appendChild(statusText); container.appendChild(row); });
  },

  renderAllJobs(){
    const container=document.getElementById('allJobsStack'); if(!container) return; container.innerHTML=''; if(this.jobOrder.length===0){ container.innerHTML='<div style="padding:8px; color:var(--text-muted); font-size:11px;">No jobs yet — start a run to see separate jobs and rectangles confirmations as it makes clicks.</div>'; return; }
    const toShow=[...this.jobOrder].reverse().slice(0,10);
    toShow.forEach(jobId=>{ const statuses=this.jobStatuses[jobId]||{}; const successCount=Object.values(statuses).filter(s=>s.status==='success').length; const failedCount=Object.values(statuses).filter(s=>s.status==='failed').length; const waitingCount=Object.values(statuses).filter(s=>s.status==='waiting' || s.status==='paused').length; const statusOverall=failedCount>0?'failed':waitingCount>0?'paused':successCount===this.blocks.length?'completed':'running'; const color=statusOverall==='completed'?'#4ADE80':statusOverall==='failed'?'#FF6B6B':statusOverall==='paused'?'#FFAA00':'#5AA9FF'; const jobDiv=document.createElement('div'); jobDiv.style.cssText=`margin:6px 0; border:1px solid ${color}; border-radius:8px; overflow:hidden;`; const header=document.createElement('div'); header.style.cssText=`display:flex; justify-content:space-between; align-items:center; padding:6px 8px; background:var(--bg-input); cursor:pointer; font-size:11px; font-weight:600;`; header.innerHTML=`<span>Job ${jobId.slice(0,8)} — ${successCount}/${this.blocks.length} ${statusOverall}${waitingCount?' ⏸':''}</span><span style="font-size:10px; color:var(--text-muted);">${Object.keys(statuses).length} blocks</span>`; header.addEventListener('click',()=>{ const body=jobDiv.querySelector('.job-body'); if(body) body.style.display=body.style.display==='none'?'block':'none'; }); const body=document.createElement('div'); body.className='job-body'; body.style.cssText='padding:4px; max-height:200px; overflow-y:auto;'; this.blocks.forEach(block=>{ const st=statuses[block.id]||statuses[block.block_id]||{status:'pending'}; const row=document.createElement('div'); const sc=st.status==='success'?'#4ADE80':st.status==='failed'?'#FF6B6B':st.status==='waiting'?'#5AA9FF':st.status==='paused'?'#FFAA00':st.status==='running'?'#FFAA00':'#666'; row.style.cssText=`display:flex; gap:4px; align-items:center; padding:3px 6px; font-size:10px; border-left:2px solid ${block.color}; margin:2px 0; background:var(--bg-input); border-radius:4px;`; row.innerHTML=`<span class="material-icons" style="font-size:12px; color:${sc};">${st.status==='success'?'check_circle':st.status==='failed'?'error':st.status==='waiting'?'hourglass_top':st.status==='paused'?'pause_circle':st.status==='running'?'play_circle':'hourglass_empty'}</span><span style="flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${this.esc(block.custom_name||block.name)}</span><span style="color:${sc}; font-size:9px; font-weight:600;">${st.status}</span>${st.rect?`<span style="font-size:8px; color:var(--text-muted);" title="${JSON.stringify(st.rect)}">📐 ${Math.round(st.rect.width)}×${Math.round(st.rect.height)}</span>`:''}`; body.appendChild(row); }); jobDiv.appendChild(header); jobDiv.appendChild(body); container.appendChild(jobDiv); });
  },
};

if (typeof window !== 'undefined') window.ActionBlocksPanel = ActionBlocksPanel;

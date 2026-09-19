/* block-render.js — DOM rendering for Action Blocks (C7)
   Pure render helpers, no bridge persistence.
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksRender = {
  esc(s) {
    const h = window.UIHelpers && window.UIHelpers.esc;
    if (h) return h(s);
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  },

  badgeClassForBlock(block) {
    const cat = (block.category || 'action').toLowerCase();
    const map = {
      visual: 'ab-badge-visual',
      highlight: 'ab-badge-visual',
      observe: 'ab-badge-visual',
      action: 'ab-badge-action',
      verify: 'ab-badge-verify',
      wait: 'ab-badge-wait',
      process: 'ab-badge-wait',
      persist: 'ab-badge-persist',
      security: 'ab-badge-security',
      control: 'ab-badge-control',
    };
    return map[cat] || 'ab-badge-action';
  },

  _statusForBlock(block, state) {
    const jobId = state.currentJobId;
    if (!jobId) return null;
    const statuses = state.jobStatuses[jobId];
    if (!statuses) return null;
    return statuses[block.id] || null;
  },

  _classForBlock(block, idx, state, status) {
    const parts = ['ab-block'];
    if (block.enabled === false) parts.push('ab-block--disabled');
    if (idx === state.selectedIdx) parts.push('ab-block--selected');
    if (status) parts.push(`ab-block--${status}`);
    return parts.join(' ');
  },

  _innerHtmlForBlock(block, status) {
    const badgeClass = this.badgeClassForBlock(block);
    const iconHtml = block.icon ? `<span class="material-icons ab-block__icon" style="color:${this.esc(block.color)}">${this.esc(block.icon)}</span>` : '';
    const req = block.required ? '<span class="ab-badge ab-badge-required">REQ</span>' : '';
    const st = status ? `<span class="ab-badge ab-badge-${this.esc(status)}">${this.esc(status)}</span>` : '';
    const custom = block.custom_name ? ` <small>(${this.esc(block.custom_name)})</small>` : '';
    return `
      <div class="ab-block__main">
        <span class="ab-block__drag">⋮⋮</span>
        ${iconHtml}
        <span class="ab-block__name">${this.esc(block.name)}${custom}</span>
        <span class="ab-block__spacer"></span>
        <span class="ab-badge ${badgeClass}">${this.esc(block.category || 'action')}</span>
        ${req}${st}
      </div>
      <div class="ab-block__actions">
        <label class="ab-toggle"><input type="checkbox" ${block.enabled !== false ? 'checked' : ''} ${block.required ? 'disabled' : ''} data-action="toggle" data-block-id="${this.esc(block.id)}" /> on</label>
        <button class="ab-btn ab-btn--sm" data-action="config" data-block-id="${this.esc(block.id)}">⚙</button>
        ${!block.required ? `<button class="ab-btn ab-btn--sm ab-btn--danger" data-action="delete" data-block-id="${this.esc(block.id)}">✕</button>` : ''}
      </div>
    `;
  },

  createBlockElement(block, idx, state) {
    const status = this._statusForBlock(block, state);
    const el = document.createElement('div');
    el.className = this._classForBlock(block, idx, state, status);
    el.draggable = true;
    el.dataset.index = String(idx);
    el.dataset.blockId = block.id;
    el.innerHTML = this._innerHtmlForBlock(block, status);
    return el;
  },

  _chipElement(name, cls) {
    const chip = document.createElement('span');
    chip.className = cls;
    chip.innerHTML = `<span class="ab-chip__name">${this.esc(name)}</span><button class="ab-chip__del" title="Delete">✕</button>`;
    return chip;
  },

  renderStackChips(root, presets, onLoad, onDelete) {
    const container = root.querySelector('#stackPresetChips');
    if (!container) return;
    container.innerHTML = '';
    presets.forEach(p => {
      const chip = this._chipElement(p.name, 'ab-chip ab-chip--stack');
      chip.querySelector('.ab-chip__name').addEventListener('click', () => onLoad(p));
      chip.querySelector('.ab-chip__del').addEventListener('click', (e) => { e.stopPropagation(); onDelete(p.name); });
      container.appendChild(chip);
    });
  },

  renderCustomChips(root, customs, onAdd, onDelete) {
    const container = root.querySelector('#customBlockChips');
    if (!container) return;
    container.innerHTML = '';
    customs.forEach(entry => {
      const chip = this._chipElement(entry.name, 'ab-chip ab-chip--custom');
      chip.querySelector('.ab-chip__name').addEventListener('click', () => onAdd(entry));
      chip.querySelector('.ab-chip__del').addEventListener('click', (e) => { e.stopPropagation(); onDelete(entry.name); });
      container.appendChild(chip);
    });
  },

  renderAddMenu(root, builtinCatalog, onAddBuiltin) {
    const menu = root.querySelector('#ab-add-menu');
    if (!menu) return;
    menu.innerHTML = '';
    builtinCatalog.forEach(b => {
      const item = document.createElement('button');
      item.className = 'ab-add-item';
      item.dataset.blockType = b.block_id;
      item.innerHTML = `<span class="material-icons" style="font-size:16px;color:${this.esc(b.defaults?.color || '#888')}">${this.esc(b.icon || 'extension')}</span> ${this.esc(b.name)} <small>${this.esc(b.category || '')}</small>`;
      item.addEventListener('click', () => onAddBuiltin(b.block_id));
      menu.appendChild(item);
    });
  },

  _bindBlockItemEvents(el, block, idx, handlers) {
    el.addEventListener('click', (e) => {
      const actEl = e.target.closest('[data-action]');
      if (!actEl) { handlers.onSelect(idx); return; }
      const action = actEl.dataset.action;
      if (action === 'toggle') handlers.onToggle(block.id, actEl.checked);
      else if (action === 'config') handlers.onConfig(idx);
      else if (action === 'delete') handlers.onDelete(block.id);
    });
    el.addEventListener('dragstart', (e) => handlers.onDragStart(e, idx));
    el.addEventListener('dragover', (e) => handlers.onDragOver(e, idx));
    el.addEventListener('drop', (e) => handlers.onDrop(e, idx));
    el.addEventListener('dragend', () => handlers.onDragEnd());
  },

  renderBlockList(root, blocks, storeState, handlers) {
    const list = root.querySelector('#actionBlocksStack');
    if (!list) return;
    list.innerHTML = '';
    blocks.forEach((block, idx) => {
      const el = this.createBlockElement(block, idx, storeState);
      this._bindBlockItemEvents(el, block, idx, handlers);
      list.appendChild(el);
    });
  },

  renderJobStack(spec) {
    const { root, jobId, blocks, statuses, onBlockClick } = spec;
    const container = root.querySelector('#jobActionStack');
    if (!container) return;
    container.innerHTML = '';
    const jobStatus = statuses[jobId] || {};
    blocks.forEach(block => {
      const status = jobStatus[block.id] || 'pending';
      const item = document.createElement('div');
      item.className = `ab-job-block ab-job-block--${this.esc(status)}`;
      item.dataset.blockId = block.id;
      item.innerHTML = `<span class="ab-job-block__icon">${this.esc(block.icon || '')}</span><span class="ab-job-block__name">${this.esc(block.name)}</span><span class="ab-job-block__status">${this.esc(status)}</span>`;
      item.addEventListener('click', () => onBlockClick(block.id));
      container.appendChild(item);
    });
  },

  renderAllJobs(spec) {
    const { root, jobOrder, currentJobId, jobStatuses, onSelectJob } = spec;
    const container = root.querySelector('#allJobsStack');
    if (!container) return;
    container.innerHTML = '';
    jobOrder.forEach(jid => {
      const btn = document.createElement('button');
      btn.className = `ab-job-tab${jid === currentJobId ? ' ab-job-tab--active' : ''}`;
      btn.textContent = jid.slice(0, 8);
      btn.addEventListener('click', () => onSelectJob(jid));
      container.appendChild(btn);
    });
  },

  updateFooter(root, state) {
    const pauseEl = root.querySelector('#ab-pause-indicator');
    if (pauseEl) {
      if (state._isPaused) {
        pauseEl.textContent = `⏸ Paused${state._pauseReason ? ': ' + state._pauseReason : ''}`;
        pauseEl.style.display = '';
      } else pauseEl.style.display = 'none';
    }
    const countEl = root.querySelector('#ab-block-count');
    if (countEl) countEl.textContent = `${state.blocks.length} blocks`;
  },
};

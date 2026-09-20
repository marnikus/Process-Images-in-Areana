/* block-render.js — DOM rendering for the Action Blocks stack (C7)
   DOM contract = index.html + css/arena.css ("target screenshot" design):
     #actionBlocksStack > .action-block[data-block-id][data-index] rows with
       .ab-drag-handle .ab-block-icon .ab-block-info(.ab-block-title .ab-block-meta)
       .ab-badge.ab-badge-<category> [.ab-badge-required] [.ab-badge-status]
       .ab-block-controls > .ab-check | .ab-edit-btn | .ab-delete-btn  (all .ab-act[data-action])
     row states: .selected .ab-disabled .dragging .drag-over .ab-status-<status>
     (footer counters, preset chips and job views live in block-views.js)
   B11 (2026-10-07): the previous renderer targeted ids that never existed in
   index.html (#panel-action-blocks, #ab-block-list, …) and returned silently —
   the badge said "16 BLOCKS" while the list stayed empty. Containers are now
   resolved by the real ids only; rows are built with DOM nodes (no innerHTML).
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksRender = {
  STATUSES: ['running', 'waiting', 'success', 'failed', 'skipped'],
  /* Block definitions name two icons Material Icons has no ligature for
     (they would render as literal text). Presentation-only aliases. */
  ICON_ALIASES: { captcha: 'security', await_result: 'hourglass_empty' },

  el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  },

  icon(name, cls, color) {
    const i = this.el('span', `material-icons ${cls || ''}`.trim(), this.ICON_ALIASES[name] || name || 'extension');
    if (color) i.style.color = color;
    return i;
  },

  stackEl() { return document.getElementById('actionBlocksStack'); },

  badgeClassForBlock(block) {
    const cat = (block.category || 'action').toLowerCase();
    const known = ['visual', 'highlight', 'observe', 'action', 'verify', 'wait', 'process', 'persist', 'security', 'control'];
    return `ab-badge-${known.includes(cat) ? cat : 'action'}`;
  },

  displayName(block) { return block.custom_name || block.name || block.block_id || 'block'; },

  metaText(block) {
    const parts = [block.block_id || ''];
    if (block.selector) parts.push(block.selector);
    if (block.timeout_ms) parts.push(`${block.timeout_ms}ms`);
    return parts.filter(Boolean).join(' · ');
  },

  /** Live status string for a block in the current job ('running' | … | null). */
  statusOf(block, state) {
    const perJob = state && state.jobStatuses && state.currentJobId ? state.jobStatuses[state.currentJobId] : null;
    const st = perJob ? perJob[block.id] : null;
    if (!st) return null;
    return typeof st === 'string' ? st : (st.status || null);
  },

  _rowClass(block, idx, state, status) {
    const parts = ['action-block'];
    if (block.enabled === false) parts.push('ab-disabled');
    if (idx === state.selectedIdx) parts.push('selected');
    if (status) parts.push(`ab-status-${status}`);
    return parts.join(' ');
  },

  _info(block) {
    const info = this.el('div', 'ab-block-info');
    const title = this.el('div', 'ab-block-title');
    title.appendChild(document.createTextNode(this.displayName(block)));
    if (block.custom_name && block.name) title.appendChild(this.el('small', 'ab-block-orig', ` (${block.name})`));
    info.appendChild(title);
    info.appendChild(this.el('div', 'ab-block-meta', this.metaText(block)));
    info.title = block.description || '';
    return info;
  },

  _badges(block, status) {
    const out = [this.el('span', `ab-badge ${this.badgeClassForBlock(block)}`, block.category || 'action')];
    if (block.required) out.push(this.el('span', 'ab-badge ab-badge-required', 'REQ'));
    if (status) out.push(this.el('span', 'ab-badge ab-badge-status', status));
    return out;
  },

  /** spec = { cls, action, title, icon, label? } → <button class="… ab-act" data-action> */
  _button(spec) {
    const btn = this.el('button', `${spec.cls} ab-act`);
    btn.dataset.action = spec.action;
    btn.title = spec.title;
    btn.appendChild(this.icon(spec.icon));
    if (spec.label) btn.appendChild(this.el('span', '', spec.label));
    return btn;
  },

  _controls(block) {
    const box = this.el('div', 'ab-block-controls');
    const check = this.el('input', 'ab-check ab-act');
    check.type = 'checkbox';
    check.checked = block.enabled !== false;
    check.disabled = !!block.required;
    check.title = block.required ? 'Required block — always on' : 'Enable / disable block';
    check.dataset.action = 'toggle';
    box.appendChild(check);
    box.appendChild(this._button({ cls: 'ab-edit-btn', action: 'config', title: 'Edit in Block Config', icon: 'tune', label: 'Edit' }));
    if (!block.required) box.appendChild(this._button({ cls: 'ab-delete-btn', action: 'delete', title: 'Delete block', icon: 'delete' }));
    return box;
  },

  createBlockElement(block, idx, state) {
    const status = this.statusOf(block, state);
    const row = this.el('div', this._rowClass(block, idx, state, status));
    row.draggable = true;
    row.dataset.index = String(idx);
    row.dataset.blockId = block.id;
    row.style.setProperty && row.style.setProperty('--block-color', block.color || '#888');
    row.appendChild(this.icon('drag_indicator', 'ab-drag-handle'));
    row.appendChild(this.icon(block.icon, 'ab-block-icon', block.color));
    row.appendChild(this._info(block));
    this._badges(block, status).forEach((b) => row.appendChild(b));
    row.appendChild(this._controls(block));
    return row;
  },

  _onRowClick(e, block, idx, handlers) {
    const act = e.target && e.target.closest ? e.target.closest('.ab-act') : null;
    if (!act) { handlers.onSelect(idx); return; }
    const action = act.dataset.action;
    if (action === 'toggle') handlers.onToggle(block.id, !!act.checked);
    else if (action === 'config') handlers.onConfig(idx);
    else if (action === 'delete') handlers.onDelete(block.id);
  },

  _bindDrag(el, idx, handlers) {
    el.addEventListener('dragstart', (e) => { el.classList.add('dragging'); handlers.onDragStart(e, idx); });
    el.addEventListener('dragover', (e) => { el.classList.add('drag-over'); handlers.onDragOver(e, idx); });
    el.addEventListener('dragleave', () => el.classList.remove('drag-over'));
    el.addEventListener('drop', (e) => { el.classList.remove('drag-over'); handlers.onDrop(e, idx); });
    el.addEventListener('dragend', () => { el.classList.remove('dragging'); handlers.onDragEnd(); });
  },

  _bindBlockItemEvents(el, block, idx, handlers) {
    el.addEventListener('click', (e) => this._onRowClick(e, block, idx, handlers));
    el.addEventListener('dblclick', () => handlers.onHighlight && handlers.onHighlight(block));
    this._bindDrag(el, idx, handlers);
  },

  renderBlockList(blocks, state, handlers) {
    const list = this.stackEl();
    if (!list) return;
    list.innerHTML = '';
    if (!blocks.length) {
      list.appendChild(this.el('div', 'ab-stack-empty', 'No blocks — press Reset to restore the default stack'));
      return;
    }
    blocks.forEach((block, idx) => {
      const row = this.createBlockElement(block, idx, state);
      this._bindBlockItemEvents(row, block, idx, handlers);
      list.appendChild(row);
    });
  },

  rows() {
    const list = this.stackEl();
    return list ? Array.from(list.children) : [];
  },

  _rowFor(blockId) {
    return this.rows().find((r) => r.dataset && r.dataset.blockId === blockId) || null;
  },

  /** Live per-row status without a full re-render (keeps focus/drag state). */
  markRowStatus(blockId, status) {
    const row = this._rowFor(blockId);
    if (!row) return;
    this.STATUSES.forEach((s) => row.classList.remove(`ab-status-${s}`));
    if (status) row.classList.add(`ab-status-${status}`);
    let badge = row.querySelector('.ab-badge-status');
    if (!badge && status) {
      badge = this.el('span', 'ab-badge ab-badge-status');
      row.insertBefore(badge, row.querySelector('.ab-block-controls'));
    }
    if (badge) { badge.textContent = status || ''; badge.style.display = status ? '' : 'none'; }
  },

  clearRowStatuses() {
    this.rows().forEach((row) => this.markRowStatus(row.dataset.blockId, null));
  },
};

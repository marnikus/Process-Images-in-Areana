/* block-config.js — Block Config window: head + form + debounced autosave (C7)
   DOM contract (index.html #winBlockConfig + css/arena.css "screenshot 2"):
     #blockConfigHead  > .bc-title-row (.bc-title-icon .bc-title-text .bc-badge…) | .bc-head-empty
     #blockConfigForm  > .block-config-win > .bc-card > .bc-hint + .bc-row* (ActionBlocksFields)
   B11 (2026-10-07): used to target #panel-action-blocks / #ab-config-form,
   which never existed → no form ever appeared and flushSave threw on null.
   Form events are bound ONCE (Boot.bindOnce); the form is rebuilt only when
   the shown block changes, so a live re-render never eats a half-typed edit.
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksConfig = {
  _saveTimer: null,
  _shownId: null,
  _fields() { return window.ActionBlocksFields; },
  headEl() { return document.getElementById('blockConfigHead'); },
  formEl() { return document.getElementById('blockConfigForm'); },

  _el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  },

  _badge(cls, text) { return this._el('span', `bc-badge ${cls}`, text); },

  _titleText(block) { return block.custom_name || block.name || block.block_id; },

  _titleRow(block) {
    const row = this._el('div', 'bc-title-row');
    row.appendChild(window.ActionBlocksRender.icon(block.icon, 'bc-title-icon', block.color));
    row.appendChild(this._el('span', 'bc-title-text', this._titleText(block)));
    row.appendChild(this._badge('bc-badge-id', block.block_id));
    row.appendChild(this._badge('bc-badge-cat', block.category || 'action'));
    if (block.required) row.appendChild(this._badge('bc-badge-cat', 'required'));
    return row;
  },

  renderHead(block) {
    const head = this.headEl();
    if (!head) return;
    head.innerHTML = '';
    if (block) { head.appendChild(this._titleRow(block)); return; }
    head.appendChild(this._el('span', 'bc-head-empty', 'Select a block to configure — all params storable in preset JSON, rect duration configurable'));
  },

  _emptyForm(form) {
    form.innerHTML = '';
    form.classList.add('empty');
    form.appendChild(this._el('div', 'bc-hint', 'Click a block in the stack (or its Edit button) to tune selectors, timings and visual confirmation. Changes save automatically.'));
  },

  buildForm(block, labels) {
    const form = this.formEl();
    if (!form) return;
    if (!block) { this._emptyForm(form); return; }
    form.innerHTML = '';
    form.classList.remove('empty');
    const win = this._el('div', 'block-config-win');
    const card = this._el('div', 'bc-card');
    if (block.description) card.appendChild(this._el('div', 'bc-hint', block.description));
    this._fields().orderedDefs(block, labels).forEach((def) => card.appendChild(this._fields().row(def, block)));
    win.appendChild(card);
    form.appendChild(win);
  },

  /** Show `block` (null = empty state); rebuilds only when the block changes or `force`. */
  showConfig(block, labels, force) {
    const id = block ? block.id : null;
    if (!force && id === this._shownId) return;
    this._shownId = id;
    this.renderHead(block);
    this.buildForm(block, labels);
  },

  _onFieldEvent(e, getBlock, onSave) {
    const input = e.target && e.target.closest ? e.target.closest('.bc-field') : null;
    if (!input) return;
    this.scheduleSave(getBlock, onSave);
  },

  /** Bind once per form element (init-time); idempotent through Boot.bindOnce. */
  bindFormEvents(getSelectedBlock, onSave) {
    const form = this.formEl();
    if (!form) return;
    const handler = (e) => this._onFieldEvent(e, getSelectedBlock, onSave);
    const bind = (ev) => (window.Boot ? window.Boot.bindOnce(form, ev, handler, 'ab-config') : form.addEventListener(ev, handler));
    bind('input');
    bind('change');
  },

  scheduleSave(getSelectedBlock, onSave) {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this.flushSave(getSelectedBlock, onSave), 400);
  },

  flushSave(getSelectedBlock, onSave) {
    clearTimeout(this._saveTimer);
    this._saveTimer = null;
    const block = getSelectedBlock();
    if (!block) return;
    this._fields().apply(block, this._fields().readForm(this.formEl()));
    onSave(block);
  },
};

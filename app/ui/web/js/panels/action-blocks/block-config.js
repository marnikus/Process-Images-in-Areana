/* block-config.js — config panel rendering & editing (C7)
   Handles config form for a single block, debounced save.
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksConfig = {
  _saveTimer: null,

  fieldDefs() {
    return [
      { key: 'selector', label: 'CSS Selector', type: 'text', placeholder: 'e.g. [data-testid=attach]' },
      { key: 'label_selector', label: 'Label Selector', type: 'text' },
      { key: 'match_text', label: 'Match Text', type: 'text' },
      { key: 'match_mode', label: 'Match Mode', type: 'select', options: ['contains', 'exact', 'regex'] },
      { key: 'click_enabled', label: 'Click Enabled', type: 'checkbox' },
      { key: 'click_selector', label: 'Click Selector', type: 'text' },
      { key: 'fallback_selector', label: 'Fallback Selector', type: 'text' },
      { key: 'fallback_text', label: 'Fallback Text', type: 'text' },
      { key: 'highlight_enabled', label: 'Highlight Enabled', type: 'checkbox' },
      { key: 'color', label: 'Color', type: 'color' },
      { key: 'timeout_ms', label: 'Timeout (ms)', type: 'number' },
      { key: 'pre_delay_ms', label: 'Pre Delay (ms)', type: 'number' },
      { key: 'highlight_ms', label: 'Highlight (ms)', type: 'number' },
      { key: 'confirm_pause_ms', label: 'Confirm Pause (ms)', type: 'number' },
      { key: 'enabled', label: 'Enabled', type: 'checkbox' },
      { key: 'custom_name', label: 'Custom Name', type: 'text' },
    ];
  },

  _createSelectInput(def, block) {
    const input = document.createElement('select');
    def.options.forEach(opt => {
      const o = document.createElement('option');
      o.value = opt;
      o.textContent = opt;
      if (block[def.key] === opt) o.selected = true;
      input.appendChild(o);
    });
    return input;
  },

  _createCheckboxInput(def, block) {
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!block[def.key];
    return input;
  },

  _createTextInput(def, block) {
    const input = document.createElement('input');
    if (def.type === 'color') input.type = 'color';
    else if (def.type === 'number') input.type = 'number';
    else input.type = 'text';
    input.value = block[def.key] != null ? String(block[def.key]) : '';
    if (def.placeholder) input.placeholder = def.placeholder;
    return input;
  },

  _inputForDef(def, block) {
    if (def.type === 'select') return this._createSelectInput(def, block);
    if (def.type === 'checkbox') return this._createCheckboxInput(def, block);
    return this._createTextInput(def, block);
  },

  _fieldRow(def, block) {
    const row = document.createElement('div');
    row.className = 'ab-field';
    const label = document.createElement('label');
    label.className = 'ab-field__label';
    label.textContent = def.label;
    const wrap = document.createElement('div');
    wrap.className = 'ab-field__input';
    const input = this._inputForDef(def, block);
    input.dataset.fieldKey = def.key;
    wrap.appendChild(input);
    row.appendChild(label);
    row.appendChild(wrap);
    return row;
  },

  _appendSaveButton(form) {
    const btn = document.createElement('button');
    btn.className = 'ab-btn ab-btn--primary';
    btn.textContent = 'Save';
    btn.dataset.action = 'save-config';
    form.appendChild(btn);
  },

  buildForm(root, block) {
    const form = root.querySelector('#ab-config-form');
    if (!form) return;
    form.innerHTML = '';
    if (!block) {
      form.innerHTML = '<div class="ab-empty">Select a block to configure</div>';
      return;
    }
    this.fieldDefs().forEach(def => {
      form.appendChild(this._fieldRow(def, block));
    });
    this._appendSaveButton(form);
  },

  _onFieldInput(e, getBlock, onSave) {
    const input = e.target.closest('[data-field-key]');
    if (!input) return;
    this.scheduleSave(getBlock, onSave);
  },

  bindFormEvents(root, getSelectedBlock, onSave) {
    const form = root.querySelector('#ab-config-form');
    if (!form) return;
    form.addEventListener('input', (e) => this._onFieldInput(e, getSelectedBlock, onSave));
    form.addEventListener('change', (e) => this._onFieldInput(e, getSelectedBlock, onSave));
    form.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action="save-config"]');
      if (!btn) return;
      e.preventDefault();
      this.flushSave(getSelectedBlock, onSave);
    });
  },

  readFormValues(root) {
    const form = root.querySelector('#ab-config-form');
    if (!form) return {};
    const values = {};
    form.querySelectorAll('[data-field-key]').forEach(input => {
      const key = input.dataset.fieldKey;
      if (input.type === 'checkbox') values[key] = input.checked;
      else if (input.type === 'number') {
        const n = Number(input.value);
        values[key] = Number.isFinite(n) ? n : 0;
      } else values[key] = input.value;
    });
    return values;
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
    const root = document.getElementById('panel-action-blocks');
    Object.assign(block, this.readFormValues(root));
    onSave();
  },

  showConfig(root, idx, blocks) {
    const block = blocks[idx] || null;
    this.buildForm(root, block);
  },
};

/* block-fields.js — Block Config field schema + input builders (B11 split)
   One row per editable ActionBlock attribute; the block type's catalog
   `labels` (get_builtin_blocks) decide which rows come first and how they
   are worded, exactly like the Old App "Tune" panel. Label keys that are
   not ActionBlock attributes (suffix, overwrite, duration_ms, …) live in
   `block.extra`. Markup = css/arena.css `.bc-*` design.
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.ActionBlocksFields = {
  defs() {
    return [
      { key: 'custom_name', label: 'Custom Name (shown in stack & logs)', type: 'text' },
      { key: 'selector', label: 'CSS Selector', type: 'text', placeholder: 'e.g. [data-testid=attach]' },
      { key: 'label_selector', label: 'Label Selector (inner text element)', type: 'text' },
      { key: 'match_text', label: 'Match Text', type: 'text' },
      { key: 'match_mode', label: 'Match Mode', type: 'select', options: ['contains', 'exact', 'regex'] },
      { key: 'click_enabled', label: 'Click after found', type: 'checkbox' },
      { key: 'click_selector', label: 'Click Selector (inner element)', type: 'text' },
      { key: 'fallback_selector', label: 'Fallback Selector', type: 'text' },
      { key: 'fallback_text', label: 'Fallback Text', type: 'text' },
      { key: 'highlight_enabled', label: 'Visual confirmation outline', type: 'checkbox' },
      { key: 'color', label: 'Highlight Color', type: 'color' },
      { key: 'timeout_ms', label: 'Timeout (ms)', type: 'number' },
      { key: 'pre_delay_ms', label: 'Pre Delay (ms)', type: 'number' },
      { key: 'highlight_ms', label: 'Highlight duration (ms)', type: 'number' },
      { key: 'confirm_pause_ms', label: 'Confirm Pause (ms)', type: 'number' },
      { key: 'enabled', label: 'Enabled', type: 'checkbox' },
    ];
  },

  _extraDef(key, label, value) {
    const type = typeof value === 'boolean' ? 'checkbox' : (typeof value === 'number' ? 'number' : 'text');
    return { key, label, type, extra: true };
  },

  /** Rows for `block`: labelled (block-specific) keys first, then the generic rest. */
  orderedDefs(block, labels) {
    const all = this.defs();
    const byKey = Object.fromEntries(all.map((d) => [d.key, d]));
    const extra = (block && block.extra) || {};
    const first = Object.keys(labels || {}).map((key) => (byKey[key]
      ? { ...byKey[key], label: labels[key] }
      : this._extraDef(key, labels[key], extra[key])));
    const rest = all.filter((d) => !(labels && d.key in labels));
    return first.concat(rest);
  },

  valueOf(block, def) {
    if (!block) return '';
    return def.extra ? (block.extra || {})[def.key] : block[def.key];
  },

  _select(def, value) {
    const input = document.createElement('select');
    input.className = 'bc-input bc-select';
    (def.options || []).forEach((opt) => {
      const o = document.createElement('option');
      o.value = opt; o.textContent = opt;
      if (value === opt) o.selected = true;
      input.appendChild(o);
    });
    input.value = value != null ? String(value) : '';
    return input;
  },

  _checkbox(value) {
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.className = 'bc-checkbox';
    input.checked = !!value;
    return input;
  },

  _text(def, value) {
    const input = document.createElement('input');
    input.type = def.type === 'number' ? 'number' : 'text';
    input.className = 'bc-input' + (def.type === 'color' ? ' bc-input-color' : '');
    input.value = value != null ? String(value) : '';
    if (def.placeholder) input.placeholder = def.placeholder;
    return input;
  },

  input(def, value) {
    const node = def.type === 'select' ? this._select(def, value)
      : def.type === 'checkbox' ? this._checkbox(value) : this._text(def, value);
    node.classList.add('bc-field');
    node.dataset.fieldKey = def.key;
    if (def.extra) node.dataset.extra = '1';
    node.id = `bcField_${def.key}`;
    return node;
  },

  /** Color rows get a swatch + native picker that both drive the text input. */
  colorControl(def, value) {
    const wrap = document.createElement('div');
    wrap.className = 'bc-control bc-control-color';
    const swatch = document.createElement('span');
    swatch.className = 'bc-color-preview';
    swatch.style.background = value || '#888';
    const text = this.input(def, value);
    const picker = document.createElement('input');
    picker.type = 'color'; picker.className = 'bc-color-picker'; picker.value = /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#888888';
    picker.addEventListener('input', () => { text.value = picker.value.toUpperCase(); swatch.style.background = text.value; });
    text.addEventListener('input', () => { swatch.style.background = text.value; });
    wrap.appendChild(swatch); wrap.appendChild(text); wrap.appendChild(picker);
    return wrap;
  },

  row(def, block) {
    const value = this.valueOf(block, def);
    const check = def.type === 'checkbox';
    const row = document.createElement('div');
    row.className = check ? 'bc-row bc-row-check' : 'bc-row';
    const label = document.createElement('label');
    label.className = 'bc-label';
    label.textContent = def.label;
    label.htmlFor = `bcField_${def.key}`;
    row.appendChild(label);
    if (def.type === 'color') { row.appendChild(this.colorControl(def, value)); return row; }
    const control = document.createElement('div');
    control.className = 'bc-control';
    control.appendChild(this.input(def, value));
    row.appendChild(control);
    return row;
  },

  _read(input) {
    if (input.type === 'checkbox') return !!input.checked;
    if (input.type === 'number') { const n = Number(input.value); return Number.isFinite(n) ? n : 0; }
    return input.value;
  },

  /** {values, extra} from every .bc-field input inside `form`. */
  readForm(form) {
    const values = {}; const extra = {};
    if (!form) return { values, extra };
    form.querySelectorAll('.bc-field').forEach((input) => {
      const key = input.dataset && input.dataset.fieldKey;
      if (!key) return;
      (input.dataset.extra ? extra : values)[key] = this._read(input);
    });
    return { values, extra };
  },

  apply(block, read) {
    Object.assign(block, read.values);
    if (Object.keys(read.extra).length) block.extra = { ...(block.extra || {}), ...read.extra };
    if ('highlight_ms' in read.values) block.highlight_duration_ms = read.values.highlight_ms;
    return block;
  },
};

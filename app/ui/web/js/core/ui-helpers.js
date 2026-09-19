/* UIHelpers — small DOM builders deduped from panels (C8)
   esc, el, chip, sortArrow, mergeParts + shared chip creators.
   RULE18: file 150-300, func ≤30, CC≤10
*/
'use strict';

window.UIHelpers = {
  esc(s) {
    const str = s === undefined || s === null ? '' : String(s);
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
  },

  el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null && text !== '') node.textContent = String(text);
    return node;
  },

  _chipTitle(opts) {
    const o = opts || {};
    const title = this.el('span', 'chip-title', (o.icon ? o.icon + ' ' : '') + (o.title || ''));
    title.title = o.title || '';
    return title;
  },

  _chipMeta(opts) {
    const o = opts || {};
    if (!o.meta) return null;
    return this.el('span', 'chip-meta', o.meta);
  },

  _chipExport(opts) {
    const o = opts || {};
    if (typeof o.onExport !== 'function') return null;
    const exp = this.el('span', 'chip-export', '⬇');
    exp.title = o.exportTitle || 'Export to file';
    return exp;
  },

  _chipDelete(opts) {
    const o = opts || {};
    const x = this.el('span', 'chip-x', '×');
    x.title = o.deleteTitle || 'Delete';
    return x;
  },

  _bindChipEvents(node, opts) {
    const o = opts || {};
    if (typeof o.onLoad === 'function') node.addEventListener('click', o.onLoad);
    const x = node.querySelector('.chip-x');
    if (x && typeof o.onDelete === 'function') {
      x.addEventListener('click', (ev) => { ev.stopPropagation(); o.onDelete(ev); });
    }
    const exp = node.querySelector('.chip-export');
    if (exp && typeof o.onExport === 'function') {
      exp.addEventListener('click', (ev) => { ev.stopPropagation(); o.onExport(ev); });
    }
  },

  chip(opts) {
    const o = opts || {};
    const node = this.el('span', 'chip' + (o.selected ? ' chip-selected' : ''));
    if (o.tooltip) node.title = o.tooltip;
    node.appendChild(this._chipTitle(o));
    const meta = this._chipMeta(o);
    if (meta) node.appendChild(meta);
    const exp = this._chipExport(o);
    if (exp) node.appendChild(exp);
    node.appendChild(this._chipDelete(o));
    this._bindChipEvents(node, o);
    return node;
  },

  sortArrow(active, direction) {
    if (!active) return '▲▼';
    return direction > 0 ? '▲' : '▼';
  },

  mergeParts(host, ...parts) {
    for (const part of parts) {
      for (const key of Object.keys(part)) {
        if (key in host) continue;
        const value = part[key];
        host[key] = typeof value === 'function' ? value.bind(host) : value;
      }
    }
    return host;
  },

  _simpleChip(name, cls, onLoad, onDelete) {
    const chip = document.createElement('span');
    chip.className = cls;
    chip.innerHTML = `<span class="ab-chip__name">${this.esc(name)}</span><button class="ab-chip__del" title="Delete">✕</button>`;
    const nameEl = chip.querySelector('.ab-chip__name');
    const delEl = chip.querySelector('.ab-chip__del');
    if (nameEl && onLoad) nameEl.addEventListener('click', () => onLoad());
    if (delEl && onDelete) delEl.addEventListener('click', (e) => { e.stopPropagation(); onDelete(); });
    return chip;
  },

  actionChip(name, onLoad, onDelete) {
    return this._simpleChip(name, 'ab-chip ab-chip--stack', onLoad, onDelete);
  },

  customChip(name, onLoad, onDelete) {
    return this._simpleChip(name, 'ab-chip ab-chip--custom', onLoad, onDelete);
  },

  bookmarkChip(url, onSelect, onRemove) {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; background:var(--bg-input); border:1px solid var(--border); border-radius:12px; padding:2px 8px; font-size:11px; cursor:pointer;';
    const txt = document.createElement('span');
    txt.textContent = url.length > 40 ? url.slice(0, 40) + '…' : url;
    txt.title = url;
    txt.addEventListener('click', () => onSelect(url));
    const del = document.createElement('span');
    del.textContent = '✕';
    del.style.cssText = 'cursor:pointer; color:var(--text-muted); margin-left:4px;';
    del.title = 'Remove';
    del.addEventListener('click', (e) => { e.stopPropagation(); onRemove(url); });
    chip.appendChild(txt);
    chip.appendChild(del);
    return chip;
  },
};

/* image-queue/store.js — C13 split: state + restore, ≤150 LOC */
'use strict';
window.ImageQueueStore = {
  _filter: 'all',
  _images: [],
  _thumbCache: {},

  get filter() { return this._filter; },
  set filter(v) { this._filter = v; },
  get images() { return this._images; },
  set images(v) { this._images = v; },
  get thumbCache() { return this._thumbCache; },

  restore(state) {
    if (!state || !state.images) return [];
    this._images = state.images;
    return this._images;
  },

  filtered() {
    if (this._filter === 'all') return this._images;
    return this._images.filter(i => i.status === this._filter);
  },

  findById(id) { return this._images.find(i => i.id === id); },

  esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); },

  basename(p) {
    if (!p) return '';
    const parts = String(p).split(/[\/\\]/);
    return parts[parts.length - 1] || String(p);
  },

  fileUrl(pathOrUrl) {
    const raw = String(pathOrUrl == null ? '' : pathOrUrl);
    if (!raw) return '';
    if (/^(file|https?|data|blob|qrc):/i.test(raw)) return raw;
    let p = raw.replace(/\\/g, '/');
    if (/^[A-Za-z]:\//.test(p)) p = '/' + p;
    if (p.charAt(0) !== '/') p = '/' + p;
    return 'file://' + encodeURI(p).replace(/#/g, '%23').replace(/\?/g, '%3F');
  },
};

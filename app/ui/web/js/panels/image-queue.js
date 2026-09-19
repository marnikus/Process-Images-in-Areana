/* image-queue.js — facade C13 split into store/thumbs/render/actions, RULE18 file 150-300 */
'use strict';

const ImageQueue = {
  _store: null,
  _thumbs: null,
  _render: null,
  _actions: null,

  get _filter() { return this._store ? this._store.filter : 'all'; },
  set _filter(v) { if (this._store) this._store.filter = v; },
  get _images() { return this._store ? this._store.images : []; },
  set _images(v) { if (this._store) this._store.images = v; },
  get _thumbCache() { return this._store ? this._store.thumbCache : {}; },

  init() {
    this._store = window.ImageQueueStore;
    this._thumbs = window.ImageQueueThumbs;
    this._render = window.ImageQueueRender;
    this._actions = window.ImageQueueActions;
    this._bindToolbar();
    this._bindTable();
  },

  _bindToolbar() {
    const filterSel = document.getElementById('queueFilter');
    if (filterSel) filterSel.addEventListener('change', (e) => {
      this._filter = e.target.value;
      this.render(this._images);
    });
    document.getElementById('queueSelectAllBtn')?.addEventListener('click', () => this.bulkSelect(true));
    document.getElementById('queueDeselectAllBtn')?.addEventListener('click', () => this.bulkSelect(false));
    document.getElementById('queueRetryFailedBtn')?.addEventListener('click', () => this.retryFailed());
    document.getElementById('queueResetBtn')?.addEventListener('click', () => this.resetAll());
    document.getElementById('queueDropAiBtn')?.addEventListener('click', () => this.filterAi(false));
    document.getElementById('queueKeepAiBtn')?.addEventListener('click', () => this.filterAi(true));
    document.getElementById('queueClearListBtn')?.addEventListener('click', () => this.clearList());
  },

  _bindTable() {
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return;
    tbody.addEventListener('click', (e) => {
      const cb = e.target.closest('input[type=checkbox]');
      if (cb && cb.dataset.imgId) { this.toggleSelect(cb.dataset.imgId, cb.checked); return; }
      const btn = e.target.closest('button');
      if (!btn) return;
      const act = btn.dataset.action;
      const id = btn.dataset.imgId;
      const p = btn.dataset.path;
      const pathType = btn.dataset.pathType;
      if (act === 'retry' && id) this.retryOne(id);
      else if (act === 'reset' && id) this.resetOne(id);
      else if (act === 'exclude' && id) this.excludeOne(id);
      else if (act === 'preview' && id) this.previewOne(id);
      else if (act === 'reveal') this._handleReveal({id, pathType, fallback: p});
      else if (act === 'copy') this._handleCopy({id, pathType, fallback: p});
    });
  },

  _resolvePath(opts) {
    const o = opts || {};
    const id = o.id;
    const pathType = o.pathType;
    const fallback = o.fallback || '';
    if (id && pathType) {
      const img = this._store.findById(id);
      if (!img) return '';
      return pathType === 'output' ? (img.output_path || '') : (img.absolute_path || '');
    }
    return fallback;
  },

  _handleReveal(opts) {
    const o = opts || {};
    const path = this._resolvePath({id: o.id, pathType: o.pathType, fallback: o.fallback});
    if (path) this.revealPath(path);
    else LogConsole.log('No path to reveal', 'warn');
  },

  _handleCopy(opts) {
    const o = opts || {};
    const path = this._resolvePath({id: o.id, pathType: o.pathType, fallback: o.fallback});
    if (path) this.copyPath(path);
    else LogConsole.log('No path to copy', 'warn');
  },

  restore(state) {
    const imgs = this._store.restore(state);
    if (imgs.length) this.render(imgs);
  },

  _fileUrl(p) { return this._store.fileUrl(p); },
  _basename(p) { return this._store.basename(p); },
  revealPath(p) { this._actions.revealPath(p); },
  copyPath(p) { this._actions.copyPath(p); },
  _requestThumb(id, el) { this._thumbs.request(id, el); },
  _fetchAllThumbs(imgs) { this._thumbs.fetchAll(imgs); },
  onThumbnailReady(id, payload) { this._thumbs.onReady(id, payload); },
  render(imgs) { this._render.render(imgs); },
  esc(s) { return this._store.esc(s); },
  toggleSelect(id, sel) { this._actions.toggleSelect(id, sel); },
  bulkSelect(sel) { this._actions.bulkSelect(sel); },
  retryFailed() { this._actions.retryFailed(); },
  filterAi(keep) { this._actions.filterAi(keep); },
  resetAll() { this._actions.resetAll(); },
  clearList() { this._actions.clearList(); },
  retryOne(id) { this._actions.retryOne(id); },
  resetOne(id) { this._actions.resetOne(id); },
  excludeOne(id) { this._actions.excludeOne(id); },
  previewOne(id) { this._actions.previewOne(id); },
};

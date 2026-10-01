/* image-queue.js — facade C13 split into store/thumbs/render/actions, RULE18 file 150-300
   2026-09-30: the lane never fails silently. Every module is resolved at CALL time
   (_mod): a missing file is reported ONCE by kind + file name (the merged-build /
   partial-deploy shape), a broken lane never throws per push and never touches the
   DOM, and a module that appears later renders on the next push — no restart. */
'use strict';

const ImageQueue = {
  _cache: {},          // kind → module, filled on first successful resolve (call-time, self-healing)
  _reported: null,     // kinds whose missing-module report already went out (one line each)

  _files: {
    ImageQueueStore: 'js/panels/image-queue/store.js',
    ImageQueueThumbs: 'js/panels/image-queue/thumbs.js',
    ImageQueueRender: 'js/panels/image-queue/render.js',
    ImageQueueActions: 'js/panels/image-queue/actions.js',
  },

  init() {
    this._mod('ImageQueueStore');
    this._mod('ImageQueueThumbs');
    this._mod('ImageQueueRender');
    this._mod('ImageQueueActions');
    this._bindToolbar();
    this._bindTable();
  },

  _mod(kind) {
    const mod = this._cache[kind] || window[kind];
    if (mod) {
      this._cache[kind] = mod;
      return mod;
    }
    this._reportMissing(kind);
    return null;
  },

  _reportMissing(kind) {
    if (this._reported && this._reported.has(kind)) return;   // one line per kind, never per push
    this._reported = this._reported || new Set();
    this._reported.add(kind);
    const msg = `Image Queue cannot render: ${kind} is missing (expected file: ${this._files[kind]})`;
    console.error(`[ImageQueue] ${msg}`);
    LogConsole.log(`⚠ ${msg}`, 'error');
  },

  get _filter() { const s = this._mod('ImageQueueStore'); return s ? s.filter : 'all'; },
  set _filter(v) { const s = this._mod('ImageQueueStore'); if (s) s.filter = v; },
  get _images() { const s = this._mod('ImageQueueStore'); return s ? s.images : []; },
  set _images(v) { const s = this._mod('ImageQueueStore'); if (s) s.images = v; },
  get _thumbCache() { const s = this._mod('ImageQueueStore'); return s ? s.thumbCache : {}; },

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

  _onCheckboxClick(cb) {
    if (!cb?.dataset?.imgId) return false;
    this.toggleSelect(cb.dataset.imgId, cb.checked);
    return true;
  },

  _doSimpleAction(act, id) {
    if (!id) return false;
    if (act === 'retry') { this.retryOne(id); return true; }
    if (act === 'reset') { this.resetOne(id); return true; }
    if (act === 'exclude') { this.excludeOne(id); return true; }
    if (act === 'preview') { this.previewOne(id); return true; }
    return false;
  },

  _doPathAction(act, id, pathType, p) {
    if (act === 'reveal') { this._handleReveal({id, pathType, fallback: p}); return true; }
    if (act === 'copy') { this._handleCopy({id, pathType, fallback: p}); return true; }
    return false;
  },

  _onButtonAction(btn) {
    if (!btn) return false;
    const act = btn.dataset.action;
    const id = btn.dataset.imgId;
    const p = btn.dataset.path;
    const pathType = btn.dataset.pathType;
    if (this._doSimpleAction(act, id)) return true;
    if (this._doPathAction(act, id, pathType, p)) return true;
    return false;
  },

  _handleTableClick(e) {
    const cb = e.target.closest('input[type=checkbox]');
    if (cb && this._onCheckboxClick(cb)) return;
    const btn = e.target.closest('button');
    this._onButtonAction(btn);
  },

  _bindTable() {
    const tbody = document.getElementById('queueTableBody');
    if (!tbody) return;
    tbody.addEventListener('click', (e) => this._handleTableClick(e));
  },

  _resolvePath(opts) {
    const o = opts || {};
    if (!o.id || !o.pathType) return o.fallback;
    const img = (this._st() || {}).findById(o.id);
    if (!img) return '';
    return o.pathType === 'output' ? img.output_path : img.absolute_path;
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
    // B10: any array (even empty) re-renders — a cleared queue must not keep
    // stale rows; a payload WITHOUT `images` leaves the table alone.
    const s = this._mod('ImageQueueStore');
    if (!s) return false;                    // the missing-module report already went out
    const imgs = s.restore(state);
    if (imgs) this.render(imgs);
    return true;
  },

  /* B10 — per-job row updates straight from the bridge signals.
     job_started(job_id, absolute_path): row → processing (attempt counted the
     way Python's mark_processing does). job_finished(job_id, payload): row →
     payload.status with output_path / error. The debounced full-state push
     that follows carries the same values (source of truth). */
  _st() { return this._mod('ImageQueueStore'); },
  _rd() { return this._mod('ImageQueueRender'); },

  _patchRow(img, fields) {
    if (!img) return false;
    Object.assign(img, fields);
    const r = this._rd();
    return r ? r.updateRow(img) : false;
  },

  onJobStarted(jobId, imagePath) {
    const st = this._st();
    if (!st) return false;
    const img = st.findByPath(imagePath) || st.imageForJob(jobId);
    if (!img) return false;
    st.rememberJob(jobId, img.id);
    return this._patchRow(img, { status: 'processing', attempts: (Number(img.attempts) || 0) + 1, error: '' });
  },

  _finishedFields(r) {
    const status = r.status || 'completed';
    const fields = { status };
    if (r.output_path) fields.output_path = r.output_path;
    if (r.attempts !== undefined && r.attempts !== null) fields.attempts = r.attempts;
    fields.error = status === 'failed' ? (r.error || r.message || '') : '';
    return fields;
  },

  onJobFinished(jobId, resultJson) {
    let r = resultJson;
    try { if (typeof r === 'string') r = JSON.parse(r); } catch (e) { r = {}; }
    r = r || {};
    const st = this._st();
    if (!st) return false;
    const img = st.imageForJob(jobId) || (r.image_id && st.findById(r.image_id)) || st.findByPath(r.image_path);
    st.forgetJob(jobId);
    if (!img) return false;
    return this._patchRow(img, this._finishedFields(r));
  },

  _fileUrl(p) { const s = this._st(); return s ? s.fileUrl(p) : ''; },
  _basename(p) { const s = this._st(); return s ? s.basename(p) : ''; },
  revealPath(p) { const a = this._mod('ImageQueueActions'); if (a) a.revealPath(p); },
  copyPath(p) { const a = this._mod('ImageQueueActions'); if (a) a.copyPath(p); },
  _requestThumb(id, el) { const t = this._mod('ImageQueueThumbs'); if (t) t.request(id, el); },
  _fetchAllThumbs(imgs) { const t = this._mod('ImageQueueThumbs'); if (t) t.fetchAll(imgs); },
  onThumbnailReady(id, payload) { const t = this._mod('ImageQueueThumbs'); if (t) t.onReady(id, payload); },
  render(imgs) { const r = this._rd(); if (!r) return false; r.render(imgs); return true; },
  esc(s) { const st = this._st(); return st ? st.esc(s) : ''; },
  toggleSelect(id, sel) { const a = this._mod('ImageQueueActions'); if (a) a.toggleSelect(id, sel); },
  bulkSelect(sel) { const a = this._mod('ImageQueueActions'); if (a) a.bulkSelect(sel); },
  retryFailed() { const a = this._mod('ImageQueueActions'); if (a) a.retryFailed(); },
  filterAi(keep) { const a = this._mod('ImageQueueActions'); if (a) a.filterAi(keep); },
  resetAll() { const a = this._mod('ImageQueueActions'); if (a) a.resetAll(); },
  clearList() { const a = this._mod('ImageQueueActions'); if (a) a.clearList(); },
  retryOne(id) { const a = this._mod('ImageQueueActions'); if (a) a.retryOne(id); },
  resetOne(id) { const a = this._mod('ImageQueueActions'); if (a) a.resetOne(id); },
  excludeOne(id) { const a = this._mod('ImageQueueActions'); if (a) a.excludeOne(id); },
  previewOne(id) { const a = this._mod('ImageQueueActions'); if (a) a.previewOne(id); },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.ImageQueue = ImageQueue;

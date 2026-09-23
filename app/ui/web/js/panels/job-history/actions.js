/* job-history/actions.js — the only bridge traffic of the window.
   get_job_history (first paint + refresh), clear_job_history, the history
   thumbs (own history-thumb selector — the queue thumbs keep theirs) and
   the reveal/copy path tools. */
'use strict';
window.JobHistoryActions = {
  _store() { return window.JobHistoryStore; },

  refresh() {
    const call = Boot.needBridge('get_job_history');
    if (!call) return false;
    call((res) => {
      try { window.JobHistoryPanel.onHistory(res); } catch {}
    });
    return true;
  },

  clear() {
    if (typeof confirm === 'function'
        && !confirm('Clear the job history log? Finished-job rows are removed and cannot be restored.')) {
      return false;
    }
    const call = Boot.needBridge('clear_job_history');
    if (!call) return false;
    call((res) => {
      try {
        const r = typeof res === 'string' ? JSON.parse(res) : res;
        if (r && r.ok) this.refresh();
      } catch {}
    });
    return true;
  },

  reveal(path) {
    const call = Boot.needBridge('reveal_in_explorer');
    if (call && path) call(path, () => {});
  },

  copy(path) {
    const call = Boot.needBridge('copy_path_to_clipboard');
    if (call && path) { call(path, () => {}); return; }
    try {
      if (path && navigator && navigator.clipboard) navigator.clipboard.writeText(path);
    } catch {}
  },

  _clickedButton(e) {
    if (!e || !e.target || !e.target.closest) return null;
    return e.target.closest('button[data-act]');
  },

  onTableClick(e) {
    const btn = this._clickedButton(e);
    if (!btn) return;
    const path = (btn.dataset && btn.dataset.path) || '';
    if (!path) return;
    if (btn.dataset.act === 'reveal') this.reveal(path);
    else if (btn.dataset.act === 'copy') this.copy(path);
  },

  _elFor(id) {
    if (typeof document === 'undefined' || !document.querySelector) return null;
    return document.querySelector(`img.history-thumb[data-img-id="${id}"]`);
  },

  _applyToEl(el, src) {
    if (!el) return;
    el.src = src;
    el.style.display = 'block';
  },

  _handleThumbResponse(id, el, res) {
    try {
      const r = typeof res === 'string' ? JSON.parse(res) : res;
      if (!r.ok || !r.data_url) return;
      this._store().thumbCache[id] = r.data_url;
      this._applyToEl(el || this._elFor(id), r.data_url);
    } catch {}
  },

  requestThumb(imgId, imgEl) {
    if (!imgId) return;
    const cached = this._store().thumbCache[imgId];
    if (cached) { this._applyToEl(imgEl || this._elFor(imgId), cached); return; }
    const b = window.App && window.App.bridge;
    if (!b || !b.get_image_thumbnail) return;
    try {
      b.get_image_thumbnail(imgId, (res) => this._handleThumbResponse(imgId, imgEl, res));
    } catch {}
  },

  fetchThumbs() {
    if (!document.querySelectorAll) return;
    const imgs = document.querySelectorAll('img.history-thumb[data-img-id]');
    (imgs || []).forEach((img, idx) => {
      if (idx >= 80) return;
      const id = img.getAttribute ? img.getAttribute('data-img-id') : '';
      const cached = id && this._store().thumbCache[id];
      if (cached) { this._applyToEl(img, cached); return; }
      setTimeout(() => this.requestThumb(id, img), idx * 120);
    });
  },

  onThumbReady(imgId, payloadJson) {
    try {
      const r = typeof payloadJson === 'string' ? JSON.parse(payloadJson) : payloadJson;
      if (!r.ok || !r.data_url || !imgId) return;
      this._store().thumbCache[imgId] = r.data_url;
      this._applyToEl(this._elFor(imgId), r.data_url);
    } catch {}
  },
};

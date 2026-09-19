/* image-queue/thumbs.js — thumb cache + request, ≤150 LOC, CC≤10 */
'use strict';
window.ImageQueueThumbs = {
  _store() { return window.ImageQueueStore; },

  _elFor(id, fallback) {
    return fallback || document.querySelector(`img.queue-thumb[data-img-id="${id}"]`);
  },

  _applyToEl(el, src) {
    if (!el) return;
    el.src = src;
    el.style.display = 'block';
    if (el.nextElementSibling) el.nextElementSibling.style.display = 'none';
  },

  _fromCache(id, el) {
    const cache = this._store().thumbCache;
    if (!cache[id]) return false;
    this._applyToEl(this._elFor(id, el), cache[id]);
    return true;
  },

  _handleThumbResponse(id, el, res) {
    try {
      const r = typeof res === 'string' ? JSON.parse(res) : res;
      if (!r.ok || !r.data_url) return;
      this._store().thumbCache[id] = r.data_url;
      this._applyToEl(this._elFor(id, el), r.data_url);
    } catch {}
  },

  request(imgId, imgEl) {
    if (!imgId) return;
    if (this._fromCache(imgId, imgEl)) return;
    const b = window.App && window.App.bridge;
    if (!b || !b.get_image_thumbnail) return;
    try {
      b.get_image_thumbnail(imgId, (res) => this._handleThumbResponse(imgId, imgEl, res));
    } catch {}
  },

  fetchAll(images) {
    const b = window.App && window.App.bridge;
    if (!b || !b.get_image_thumbnail) return;
    const list = (images || []).slice(0, 80);
    const cache = this._store().thumbCache;
    list.forEach((img, idx) => {
      if (cache[img.id]) {
        this._applyToEl(document.querySelector(`img.queue-thumb[data-img-id="${img.id}"]`), cache[img.id]);
        return;
      }
      setTimeout(() => this.request(img.id, null), idx * 120);
    });
  },

  onReady(imgId, payloadJson) {
    try {
      const r = typeof payloadJson === 'string' ? JSON.parse(payloadJson) : payloadJson;
      if (!r.ok || !r.data_url) return;
      this._store().thumbCache[imgId] = r.data_url;
      this._applyToEl(document.querySelector(`img.queue-thumb[data-img-id="${imgId}"]`), r.data_url);
    } catch {}
  },
};

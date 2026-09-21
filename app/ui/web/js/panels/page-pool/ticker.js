/* page-pool/ticker.js — the 1 s countdown tick, ≤120 LOC, CC≤10 (D-4).
   Element-anchored: each clock carries its own `data-cool-at`, so a stale
   snapshot can never make the value climb back up; 00:00 is the floor and an
   expiry triggers one refresh (the pool re-reads the real state). */
'use strict';
window.PagePoolTicker = {
  _store() { return window.PagePoolStore; },

  /* D-4: one tick, element-anchored. Each clock carries its own `data-cool-at`
     (the snapshot age is only the fallback), and 00:00 is a hard floor — the
     value can never climb back up or lose its slot. */
  _leftNow(el) {
    const base = parseInt(el.getAttribute('data-cool-left') || '0', 10);
    const at = parseInt(el.getAttribute('data-cool-at') || '0', 10) || this._store().snapAt;
    const elapsed = at ? Math.floor((Date.now() - at) / 1000) : 0;
    return Math.max(0, base - Math.max(0, elapsed));
  },

  _paint(el, left) {
    if (left <= 0) { el.textContent = this._store().fmt(0); return true; }
    const txt = el.textContent;
    const suffix = txt.includes('/') ? txt.slice(txt.indexOf('/')) : '';
    el.textContent = this._store().fmt(left) + (suffix ? ' ' + suffix : '');
    return false;
  },

  tick() {
    let expired = false;
    document.querySelectorAll('[data-cool-tab]').forEach(el => {
      if (this._paint(el, this._leftNow(el))) expired = true;
    });
    if (!expired) return;
    this._store().snapAt = 0;
    window.PagePoolPanel.refresh();   // the pool re-reads the real state
  },
};

/* page-pool/store.js — state + helpers, ≤100 LOC */
'use strict';
window.PagePoolStore = {
  snapshot: {total:0, steady:0, busy:0, cooling:0, free:0, pages:[]},
  snapAt: 0,

  setSnapshot(snap) {
    this.snapshot = snap;
    this.snapAt = Date.now();
  },

  fmt(totalSecs) {
    const s = Math.max(0, Math.round(totalSecs || 0));
    const m = Math.floor(s / 60), sec = s % 60;
    if (m < 60) return String(m).padStart(2,'0')+':'+String(sec).padStart(2,'0');
    return Math.floor(m/60)+':'+String(m%60).padStart(2,'0')+':'+String(sec).padStart(2,'0');
  },

  statusColor(status) {
    if (status === 'cooldown') return '#ff9500';
    if (status === 'busy' || status === 'waiting_generation') return '#4dabf7';
    if (status === 'waiting_captcha' || status === 'error') return '#ff6b6b';
    if (status === 'disconnected') return '#888';
    return '#4ade80';
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },
};

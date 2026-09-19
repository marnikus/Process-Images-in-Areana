/* page-pool.js — facade C15 ≤100 LOC, delegates to store/render/actions */
'use strict';

const PagePoolPanel = {
  _store: null,
  _render: null,
  _actions: null,

  get snapshot() { return this._store ? this._store.snapshot : {total:0, steady:0, busy:0, cooling:0, free:0, pages:[]}; },
  set snapshot(v) { if (this._store) this._store.snapshot = v; },
  get snapAt() { return this._store ? this._store.snapAt : 0; },
  set snapAt(v) { if (this._store) this._store.snapAt = v; },

  init() {
    this._store = window.PagePoolStore;
    this._render = window.PagePoolRender;
    this._actions = window.PagePoolActions;
    document.getElementById('poolRefreshBtn')?.addEventListener('click', ()=>this.refresh());
    document.getElementById('poolClearBtn')?.addEventListener('click', ()=>this.clear());
    document.getElementById('poolConnectBtn')?.addEventListener('click', ()=>this.connectFromSelect());
    setTimeout(()=>this.refresh(), 1200);
    setInterval(()=>this.refresh(), 5000);
    setInterval(()=>this.tickCountdowns(), 1000);
  },

  refresh() { return this._actions?.refresh(); },
  clear() { return this._actions?.clear(); },
  connectFromSelect() { return this._actions?.connectFromSelect(); },
  disconnect(tabId) { return this._actions?.disconnect(tabId); },
  resetCooldown(tabId) { return this._actions?.resetCooldown(tabId); },
  editCooldown(tabId) { return this._actions?.editCooldown(tabId); },
  onUpdate(payload) { return this._actions?.onUpdate(payload); },
  tickCountdowns() { return this._actions?.tickCountdowns(); },
  fmt(s) { return this._store ? this._store.fmt(s) : `${s}s`; },
  cooldownCell(p) { return this._render ? this._render.cooldownCell(p) : '—'; },
  statusColor(s) { return this._store ? this._store.statusColor(s) : '#4ade80'; },
  esc(s) { return this._store ? this._store.esc(s) : ''; },
  render(snap) { return this._render?.render(snap, this._actions); },
};

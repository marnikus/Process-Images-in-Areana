/* url-list/listeners.js — ALL DOM listeners of the URL window, bound once.

   Bug (2026-10-02): the facade bound urlAddBtn/urlInput/… itself while the
   actions module was also reachable, so a second init() (state restore)
   double-fired "Add" (→ "URL already exists" toast) and the table body got
   stacked click handlers. Now the facade delegates here and every binding
   goes through Boot.bindOnce. Element ids: urlAddBtn, urlInput,
   urlTableBody, urlReparseBtn, urlPopupBtn, urlCooldownSaveBtn. */
'use strict';

window.UrlListListeners = {
  _actions() { return window.UrlListActions; },
  _bind(id, ev, fn) {
    const el = document.getElementById(id);
    if (!el) return false;
    if (window.Boot) return window.Boot.bindOnce(el, ev, fn, `url-list:${id}:${ev}`);
    el.addEventListener(ev, fn);
    return true;
  },

  /** Returns true when the mandatory elements exist (facade skips otherwise). */
  bind(facade) {
    const addBtn = document.getElementById('urlAddBtn');
    const input = document.getElementById('urlInput');
    const tableBody = document.getElementById('urlTableBody');
    if (!addBtn || !input || !tableBody) return false;
    this._bind('urlAddBtn', 'click', () => facade.addUrl());
    this._bind('urlInput', 'keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); facade.addUrl(); } });
    this._bind('urlReparseBtn', 'click', () => facade.reparseTabs());
    this._bind('urlPopupBtn', 'click', () => facade.popupTabs());
    this._bind('urlCooldownSaveBtn', 'click', () => facade.saveCooldownConfig());
    this._bind('urlTableBody', 'click', (e) => this.onTableClick(facade, e));
    return true;
  },

  onTableClick(facade, e) {
    const chk = e.target.closest('input[type="checkbox"]');
    if (chk) { this._onCheckbox(facade, chk); return; }
    const btn = e.target.closest('button');
    if (btn) this._onButton(facade, btn);
  },

  _onCheckbox(facade, chk) {
    if (chk.dataset.action === 'toggle' && chk.dataset.urlId) facade.toggleUrl(chk.dataset.urlId);
  },

  _onButton(facade, btn) {
    const urlId = btn.dataset.urlId;
    const action = btn.dataset.action;
    if (!urlId || !action) return;
    const map = {
      test: () => facade.testUrl(urlId),
      toggle: () => facade.toggleUrl(urlId),
      remove: () => facade.removeUrl(urlId),
      edit: () => facade.editUrl(urlId),
      connect: () => facade.connectUrl(urlId),
      'stop-job': () => facade.stopJob(urlId),
    };
    if (map[action]) { map[action](); return; }
    if (action === 'cool-reset' || action === 'cool-edit') facade.coolAction(action, btn);
  },
};

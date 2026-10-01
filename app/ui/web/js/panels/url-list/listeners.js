/* url-list/listeners.js — URL window DOM listeners, bound once. */
'use strict';
window.UrlListListeners = {
  _bind(id, ev, fn) {
    const el = document.getElementById(id);
    if (!el) return false;
    if (window.Boot) return window.Boot.bindOnce(el, ev, fn, `url-list:${id}:${ev}`);
    el.addEventListener(ev, fn); return true;
  },
  _enterToAdd(facade, e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    facade.addUrl();
  },
  bind(facade) {
    const addBtn = document.getElementById('urlAddBtn'), input = document.getElementById('urlInput'), tableBody = document.getElementById('urlTableBody');
    if (!addBtn || !input || !tableBody) return false;
    this._bind('urlAddBtn', 'click', facade.addUrl.bind(facade));
    this._bind('urlInput', 'keydown', this._enterToAdd.bind(this, facade));
    this._bind('urlReparseBtn', 'click', facade.reparseTabs.bind(facade));
    this._bind('urlPopupBtn', 'click', facade.popupTabs.bind(facade));
    this._bind('urlCooldownSaveBtn', 'click', facade.saveCooldownConfig.bind(facade));
    this._bind('urlResetAllCooldownsBtn', 'click', facade.resetAllCooldowns.bind(facade));
    this._bind('urlTableBody', 'click', this.onTableClick.bind(this, facade));
    this._bind('urlTableBody', 'keydown', this.onTableKeydown.bind(this, facade));
    return true;
  },
  onTableClick(facade, e) {
    const chk = e.target.closest('input[type="checkbox"]');
    if (chk) return void (chk.dataset.action === 'toggle' && chk.dataset.urlId && facade.toggleUrl(chk.dataset.urlId));
    const btn = e.target.closest('button');
    if (!btn) return;
    if (btn.dataset.inlineField) return void facade.startInlineEdit(btn);
    this._onButton(facade, btn);
  },
  onTableKeydown(_facade, e) {
    const btn = e.target.closest('button');
    return !!(btn && btn.dataset.inlineField && window.UrlListInlineEdit?.onButtonKey(e, btn));
  },
  _onButton(facade, btn) {
    const urlId = btn.dataset.urlId, action = btn.dataset.action;
    if (!urlId || !action) return;
    if (action === 'cool-reset' || action === 'cool-edit') return void facade.coolAction(action, btn);
    ({ toggle: facade.toggleUrl, remove: facade.removeUrl, connect: facade.connectUrl, 'stop-job': facade.stopJob }[action] || (() => {})).call(facade, urlId);
  },
};

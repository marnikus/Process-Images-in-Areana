/* url-list/actions.js — CRUD + connect (cooldown lives in url-list/cooldown.js), ≤200 LOC, CC≤10 */
'use strict';
window.UrlListActions = {
  _store() { return window.UrlListStore; },
  _bridge() { return window.App && window.App.bridge; },

  addUrl() {
    const input = document.getElementById('urlInput');
    const val = input ? input.value.trim() : '';
    if (!val) return;
    const b = this._bridge();
    if (b && b.add_url) b.add_url(val, (res)=> this._onAdd(input, val, res));
  },

  _onAdd(input, val, res) {
    try {
      const r = JSON.parse(res);
      if (!r.ok) LogConsole.log('Add URL failed: ' + r.error, 'error');
      else {
        input.value = '';
        LogConsole.log('URL added: ' + val, 'success');
        // B7: never push `App.state.urls` back to Python here. Python's
        // commit_urls() already saved + recorded the undo entry, and this
        // snapshot is STALE (arena_state_updated is applied after a 250 ms
        // debounce) — pushing it made _remember_urls overwrite the rows
        // without the new one, so the row vanished ~1 s after it appeared.
      }
    } catch {}
  },

  removeUrl(id) {
    const b = this._bridge();
    if (b && b.remove_url) b.remove_url(id, () => LogConsole.log('URL removed', 'info'));
  },

  toggleUrl(id) {
    const b = this._bridge();
    if (b && b.toggle_url) b.toggle_url(id, () => {});
  },

  connectUrl(id) {
    const urlObj = this._store().snapshotUrls().find(u => u.id === id);
    let url = urlObj ? urlObj.url : '';
    if (!url) { LogConsole.log('⚠ URL not found', 'warn'); return; }
    url = this._store().extractUrl(url);
    if (this._store().shouldDebounce(url)) return;
    LogConsole.log(`🔍 Connect: finding tab for ${url}`, 'info');
    const b = this._bridge();
    if (b && b.find_tab_by_url) b.find_tab_by_url(url);
    const inp = document.getElementById('urlBookmarkInput');
    if (inp) inp.value = url;
  },

  /* Stop / Clear time moved to url-list/reset.js (2026-09-21, D-7): this frozen
     file has no headroom, and both actions must report the richer honest reply. */
  stopJob(urlId) { return window.UrlListReset && window.UrlListReset.stopJob(urlId); },

  coolAction(action, btn) { return window.UrlListReset && window.UrlListReset.coolAction(action, btn); },

  reparseTabs() {
    LogConsole.log('🔄 Reparse requested — scanning open tabs…', 'info');
    const b = this._bridge();
    if (b && b.auto_connect_scan) b.auto_connect_scan('manual');
  },

  popupTabs() {
    const b = this._bridge();
    if (b && b.popup_url_tabs) b.popup_url_tabs();
  },

};

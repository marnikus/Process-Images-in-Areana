/* url-list/crud-actions.js — CRUD/connect facade for URL rows. */
'use strict';
window.UrlListCrudActions = {
  _store() { return window.UrlListStore; },
  _bridge() { return window.App && window.App.bridge; },
  addUrl() {
    const input = document.getElementById('urlInput'), val = input ? input.value.trim() : '';
    if (!val) return;
    this._bridge()?.add_url?.(val, res => {
      try {
        const reply = JSON.parse(res);
        if (!reply.ok) return LogConsole.log('Add URL failed: ' + reply.error, 'error');
        input.value = ''; LogConsole.log('URL added: ' + val, 'success');
      } catch {}
    });
  },
  removeUrl(id) { this._bridge()?.remove_url?.(id, () => LogConsole.log('URL removed', 'info')); },
  toggleUrl(id) { this._bridge()?.toggle_url?.(id, () => {}); },
  connectUrl(id) {
    const url = this._store().extractUrl(this._store().snapshotUrls().find(u => u.id === id)?.url || '');
    if (!url) return void LogConsole.log('⚠ URL not found', 'warn');
    if (this._store().shouldDebounce(url)) return;
    LogConsole.log(`🔍 Connect: finding tab for ${url}`, 'info');
    this._bridge()?.find_tab_by_url?.(url);
    const inp = document.getElementById('urlBookmarkInput');
    if (inp) inp.value = url;
  },
  stopJob(urlId) { return window.UrlListReset?.stopJob(urlId); },
  coolAction(action, btn) { return window.UrlListReset?.coolAction(action, btn); },
  startInlineEdit(btn) { return window.UrlListInlineEdit?.start(btn); },
  saveCooldownEdit(payload, done) { return window.UrlListInlineEdit?.saveCooldown(payload, done); },
  saveJobsEdit(payload, done) { return window.UrlListInlineEdit?.saveJobs(payload, done); },
  updateResetAllButton(pages) { return window.UrlListBulkReset?.updateButton(pages); },
  resetAllCooldowns() { return window.UrlListBulkReset?.run(); },
  reparseTabs() {
    LogConsole.log('🔄 Reparse requested — scanning open tabs…', 'info');
    this._bridge()?.auto_connect_scan?.('manual');
  },
  popupTabs() { this._bridge()?.popup_url_tabs?.(); },
};

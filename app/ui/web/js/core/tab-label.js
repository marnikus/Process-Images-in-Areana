/* core/tab-label.js — what every view and log prints for a tab (D-7).
   The pool key stays the 32-hex CDP id (identity); the label is the readable
   `{email}_{4 digits}` handle, and an unknown tab falls back to the short id.
   One formatter, so the tables and the log console can never disagree. */
'use strict';
window.TabLabel = {
  /* `of(tabId)` looks the tab up in the pool snapshot; `of(tabId, page)` skips it. */
  of(tabId, page) {
    const known = page || this._page(tabId);
    const id = String(tabId || (known && known.tab_id) || '');
    return (known && known.tab_label) || id.slice(0, 8);
  },

  _page(tabId) {
    const panel = window.PagePoolPanel;
    const snap = (panel && panel.snapshot) || {};
    return (snap.pages || []).find(p => p.tab_id === tabId);
  },
};

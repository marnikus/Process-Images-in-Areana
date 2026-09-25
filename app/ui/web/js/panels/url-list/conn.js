/* url-list/conn.js — D-10 browser-identity cells (Conn method + row icon).
   New module on purpose: the 2026-09-25 firefox integration adds ZERO lines to
   the frozen url-list files — the same split the 2026-09-21 round did with cells.js. */
'use strict';
window.UrlListConn = {
  _esc(s) { return window.UrlListStore ? window.UrlListStore.esc(s) : String(s || ''); },

  /* The Tab cell's browser icon: 🦊 firefox, 🌐 chrome, none for old snapshots. */
  icon(page) {
    if (!page || !page.browser) return '';
    return page.browser === 'firefox' ? '🦊 ' : '🌐 ';
  },

  titleSuffix(page) {
    return page && page.profile ? ` — ${this._esc(page.profile)}` : '';
  },

  /* Owner §2.3: one cell = browser icon + method (`🦊 uivision` / `🌐 cdp`).
     Pooled rows only — `data-connlocked` keeps chrome's own matcher repaint
     (cdp-render) away from a row whose method the pool already states. */
  fillConnCell(tr, page) {
    const cell = tr.querySelector('.url-conn-status');
    if (!cell) return;
    if (!page) { delete tr.dataset.connlocked; return; }
    tr.dataset.connlocked = '1';
    const conn = page.browser === 'firefox' ? '🦊 uivision' : '🌐 cdp';
    cell.innerHTML = `<span style="color:var(--text-muted); font-size:11px;" title="${this._esc(page.tab_id)}">${conn}</span>`;
  },

  /* Chrome's matcher paints first (D-10); pooled rows overwrite theirs right after. */
  repaintChrome() {
    try {
      if (typeof CDPPanel !== 'undefined' && CDPPanel.updateUrlRowsConnection) CDPPanel.updateUrlRowsConnection();
    } catch { /* store not ready yet */ }
  },
};

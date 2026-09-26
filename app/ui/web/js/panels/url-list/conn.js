/* url-list/conn.js — the URL row's CONN cell: browser icon + lane (I-64, 2026-09-25).
   A linked row shows its lane: `🌐 cdp` (Chrome, keeps the tab-match evidence)
   or `🦊 uivision` (Firefox). A Firefox row never borrows a Chrome match: its
   tab is reached through Ui.Vision, never over CDP. An unlinked row keeps the
   old wording. `browser`/`conn` come from the server (derived from the tab id). */
'use strict';
const UrlListConn = {
  ICON: { chrome: '🌐', firefox: '🦊' },

  _span(color, title, text) {
    return `<span style="color:${color}; font-size:11px;" title="${title}">${text}</span>`;
  },

  _head(u) {
    const icon = this.ICON[u.browser];
    return icon && u.conn ? `${icon} ${u.conn} ` : '';
  },

  _fox(u, esc) {
    const title = `Firefox tab ${esc(u.tab_id)} — its jobs run through Ui.Vision (one macro at a time)`;
    return this._span('var(--success, #4ade80)', title, '🦊 uivision');
  },

  cell(u, match, store, esc) {
    if (u.conn === 'uivision') return this._fox(u, esc);
    const head = this._head(u);
    if (match) {
      const title = `${esc(match.title)} — ${esc(match.url)}`;
      return this._span('var(--success, #4ade80)', title, `${head}● ${esc(match.kind)} (${match.score})`);
    }
    const none = store.tabs.length === 0 ? '○ no chrome' : '○ no tab';
    return this._span('var(--text-muted)', '', `${head}${none}`);
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.UrlListConn = UrlListConn;

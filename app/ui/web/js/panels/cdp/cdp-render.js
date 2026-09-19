/* cdp/cdp-render.js — rendering for CDP panel (C7) */
'use strict';
window.CDPRender = {
  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;');
  },

  _sortTabs(tabs, store) {
    return [...(tabs || [])].sort((a, b) => {
      const aDev = store.isDevTab(a) ? 1 : 0;
      const bDev = store.isDevTab(b) ? 1 : 0;
      return aDev - bDev;
    });
  },

  _makeOption(t, store) {
    const opt = document.createElement('option');
    opt.value = t.ws_url;
    const isDev = store.isDevTab(t);
    const title = (t.title || '').slice(0, 60);
    const url = (t.url || '').slice(0, 80);
    opt.textContent = isDev ? `[DEV] ${title} — ${url}` : `${title} — ${url}`;
    opt.title = `${t.title}\n${t.url}${isDev ? '\n(DevTools)' : ''}`;
    if (isDev) opt.style.color = 'var(--text-muted)';
    return opt;
  },

  renderTabSelect(tabs, prevValue) {
    const sel = document.getElementById('tabSelect');
    if (!sel) return;
    const store = window.CDPStore;
    const prev = prevValue || sel.value;
    sel.innerHTML = '<option value=\"\">— Select Chrome Tab —</option>';
    this._sortTabs(tabs, store).forEach(t => sel.appendChild(this._makeOption(t, store)));
    if (prev) sel.value = prev;
  },

  _chipElement(url, onSelect, onRemove) {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; background:var(--bg-input); border:1px solid var(--border); border-radius:12px; padding:2px 8px; font-size:11px; cursor:pointer;';
    const txt = document.createElement('span');
    txt.textContent = url.length > 40 ? url.slice(0, 40) + '…' : url;
    txt.title = url;
    txt.addEventListener('click', () => onSelect(url));
    const del = document.createElement('span');
    del.textContent = '✕';
    del.style.cssText = 'cursor:pointer; color:var(--text-muted); margin-left:4px;';
    del.title = 'Remove';
    del.addEventListener('click', (e) => { e.stopPropagation(); onRemove(url); });
    chip.appendChild(txt);
    chip.appendChild(del);
    return chip;
  },

  renderBookmarks(payload, onSelect, onRemove) {
    try {
      const arr = typeof payload === 'string' ? JSON.parse(payload) : payload;
      const wrap = document.getElementById('urlBookmarkChips');
      if (!wrap) return;
      wrap.innerHTML = '';
      (arr || []).forEach(url => wrap.appendChild(this._chipElement(url, onSelect, onRemove)));
    } catch {}
  },

  _connCellHtml(match, store) {
    if (match) return `<span style=\"color:var(--success, #4ade80); font-size:11px;\" title=\"${this.esc(match.title)} — ${match.url}\">● ${this.esc(match.kind)} (${match.score})</span>`;
    if (store.tabs.length === 0) return `<span style=\"color:var(--text-muted); font-size:11px;\">○ no chrome</span>`;
    return `<span style=\"color:var(--text-muted); font-size:11px;\">○ no tab</span>`;
  },

  updateUrlRowsConnection(store) {
    if (!window.App || !window.App.state || !window.App.state.urls) return;
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    window.App.state.urls.forEach((u, idx) => {
      const tr = rows[idx];
      if (!tr) return;
      const connCell = tr.querySelector('.url-conn-status');
      if (!connCell) return;
      const match = store.findBestTabForUrl(u.url);
      connCell.innerHTML = this._connCellHtml(match, store);
    });
  },

  highlightMatchingTabs(store, query) {
    if (!query) return;
    const q = query.toLowerCase();
    for (const t of store.tabs) {
      const urlMatch = t.url && t.url.toLowerCase().includes(q);
      const titleMatch = t.title && t.title.toLowerCase().includes(q);
      if (urlMatch || titleMatch) {
        if (typeof LogConsole !== 'undefined') LogConsole.log(`💡 Potential match for “${query}”: ${t.title} — ${t.url}`, 'info');
        break;
      }
    }
  },

  updateChromeToolbar(cfg) {
    if (!cfg) return;
    const toolbar = document.getElementById('chromeToolbar');
    if (!toolbar) return;
    const codeEl = toolbar.querySelector('code');
    if (!codeEl) return;
    let cmd = `\"C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe\" --remote-debugging-port=${cfg.port} --user-data-dir=\"${cfg.user_data_dir}\"`;
    if (cfg.extra_args) cmd += ` ${cfg.extra_args}`;
    codeEl.textContent = cmd;
  },
};

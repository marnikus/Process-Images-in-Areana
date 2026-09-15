/* cdp.js — Chrome remote debugging: fetch tabs, match URL to open tab, show connection status per row, pick desired tab */
'use strict';

const CDPPanel = {
  tabs: [],
  connected: false,
  selectedWs: '',
  lastMatchQuery: '',

  init() {
    const refreshBtn = document.getElementById('refreshTabsBtn');
    const connectBtn = document.getElementById('connectBtn');
    const tabSelect = document.getElementById('tabSelect');
    const bookmarkInput = document.getElementById('urlBookmarkInput');
    const bookmarkConnectBtn = document.getElementById('urlBookmarkConnectBtn');
    const addBookmarkBtn = document.getElementById('addUrlBookmarkBtn');

    if (refreshBtn) refreshBtn.addEventListener('click', () => this.fetchTabs());
    if (connectBtn) connectBtn.addEventListener('click', () => this.connectSelected());
    if (tabSelect) tabSelect.addEventListener('change', (e) => {
      this.selectedWs = e.target.value;
    });
    if (bookmarkInput) {
      bookmarkInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.autoConnectBookmark();
      });
      bookmarkInput.addEventListener('input', () => {
        const v = bookmarkInput.value.trim();
        if (v.length > 3) {
          // live preview of matches? optional
        }
      });
    }
    if (bookmarkConnectBtn) bookmarkConnectBtn.addEventListener('click', () => this.autoConnectBookmark());
    if (addBookmarkBtn) addBookmarkBtn.addEventListener('click', () => this.addBookmark());

    // hook bridge signals if already available (bridge-ready will also wire)
    this.bindBridgeSignals();

    // initial fetch after short delay
    setTimeout(() => this.fetchTabs(), 800);
    setTimeout(() => this.loadBookmarks(), 900);
  },

  bindBridgeSignals() {
    // Will be called from arena-app after bridge ready as well
    if (!App.bridge) return;
    try {
      if (App.bridge.tabs_received) {
        App.bridge.tabs_received.connect((payload) => this.onTabsReceived(payload));
      }
      if (App.bridge.connection_status) {
        App.bridge.connection_status.connect((status) => this.onConnectionStatus(status));
      }
      if (App.bridge.tab_match_result) {
        App.bridge.tab_match_result.connect((query, payload) => this.onTabMatchResult(query, payload));
      }
      if (App.bridge.url_presets_updated) {
        App.bridge.url_presets_updated.connect((payload) => this.renderBookmarks(payload));
      }
    } catch (e) {
      console.warn('CDP bind signals failed', e);
    }
  },

  fetchTabs() {
    LogConsole.log('🔍 Fetching Chrome tabs from http://127.0.0.1:9222/json/list …', 'info');
    if (App.bridge && App.bridge.get_tabs) {
      try {
        App.bridge.get_tabs();
      } catch (e) {
        LogConsole.log('get_tabs failed: ' + e, 'error');
      }
    } else {
      LogConsole.log('Bridge not ready for tabs', 'warn');
    }
  },

  onTabsReceived(payload) {
    try {
      const tabs = JSON.parse(payload);
      this.tabs = tabs || [];
      this.renderTabSelect(this.tabs);
      LogConsole.log(`📑 Received ${this.tabs.length} Chrome tabs`, 'success');
      // update URL rows connection status
      this.updateUrlRowsConnection();
    } catch (e) {
      LogConsole.log('Failed to parse tabs: ' + e, 'error');
    }
  },

  renderTabSelect(tabs) {
    const sel = document.getElementById('tabSelect');
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">— Select Chrome Tab —</option>';
    tabs.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.ws_url;
      const title = (t.title || '').slice(0, 60);
      const url = (t.url || '').slice(0, 80);
      opt.textContent = `${title} — ${url}`;
      opt.title = `${t.title}\n${t.url}`;
      sel.appendChild(opt);
    });
    // try restore previous
    if (prev) sel.value = prev;
    // if bookmark input has value, highlight matching
    const bmInput = document.getElementById('urlBookmarkInput');
    if (bmInput && bmInput.value.trim()) {
      this.highlightMatchingTabs(bmInput.value.trim());
    }
  },

  highlightMatchingTabs(query) {
    if (!query) return;
    const q = query.toLowerCase();
    const sel = document.getElementById('tabSelect');
    if (!sel) return;
    // simple scoring: if url contains query, select first
    for (const t of this.tabs) {
      if ((t.url && t.url.toLowerCase().includes(q)) || (t.title && t.title.toLowerCase().includes(q))) {
        // don't auto-select, just log
        LogConsole.log(`💡 Potential match for “${query}”: ${t.title} — ${t.url}`, 'info');
        break;
      }
    }
  },

  connectSelected() {
    const sel = document.getElementById('tabSelect');
    const ws = sel ? sel.value : this.selectedWs;
    if (!ws) {
      LogConsole.log('⚠ No tab selected', 'warn');
      return;
    }
    LogConsole.log('🔗 Connecting to ' + ws.slice(0, 60) + '…', 'info');
    if (App.bridge && App.bridge.connect_tab) {
      App.bridge.connect_tab(ws);
    }
  },

  onConnectionStatus(status) {
    const dot = document.getElementById('connectionStatus');
    if (dot) {
      dot.className = 'status-dot ' + (status === 'connected' ? 'connected' : status === 'error' ? 'error' : 'disconnected');
      dot.title = status;
    }
    if (status === 'connected') {
      this.connected = true;
      LogConsole.log('✅ Chrome connected', 'success');
    } else if (status === 'disconnected') {
      this.connected = false;
      LogConsole.log('🔌 Chrome disconnected', 'warn');
    } else if (status === 'error') {
      LogConsole.log('❌ Chrome connection error', 'error');
    }
    // update url rows
    this.updateUrlRowsConnection();
  },

  autoConnectBookmark() {
    const input = document.getElementById('urlBookmarkInput');
    const query = (input ? input.value.trim() : '').trim();
    if (!query) {
      LogConsole.log('⚠ Bookmark field empty', 'warn');
      return;
    }
    LogConsole.log(`🔍 Auto-connect: finding tab for “${query}” …`, 'info');
    this.lastMatchQuery = query;
    if (App.bridge && App.bridge.find_tab_by_url) {
      App.bridge.find_tab_by_url(query);
    }
    // also remember as last
    if (App.bridge && App.bridge.set_last_url_preset) {
      App.bridge.set_last_url_preset(query);
    }
  },

  onTabMatchResult(query, payload) {
    try {
      const matches = JSON.parse(payload);
      if (!matches || matches.length === 0) {
        LogConsole.log(`❌ No Chrome tab matches “${query}”. Start Chrome with --remote-debugging-port=9222 --user-data-dir="C:\\arena-images-chrome" and open the page.`, 'error');
        return;
      }
      const best = matches[0];
      LogConsole.log(`🎯 Best match (${best.kind}, score ${best.score}): ${best.title} — ${best.url}`, 'success');
      // auto-select in dropdown
      const sel = document.getElementById('tabSelect');
      if (sel) {
        sel.value = best.ws_url;
        this.selectedWs = best.ws_url;
      }
      // auto-connect
      if (App.bridge && App.bridge.connect_tab) {
        LogConsole.log(`🔗 Auto-connecting to best match: ${best.title}`, 'info');
        App.bridge.connect_tab(best.ws_url);
      }
      // also update URL list rows if any URL equals query, mark connected
      this.updateUrlRowsConnection();
    } catch (e) {
      LogConsole.log('Tab match parse failed: ' + e, 'error');
    }
  },

  loadBookmarks() {
    if (App.bridge && App.bridge.get_url_presets) {
      try {
        App.bridge.get_url_presets((res) => {
          try {
            if (typeof res === 'string') {
              this.renderBookmarks(res);
            }
          } catch (e) {}
        });
      } catch (e) {
        // fallback sync
        try {
          const res = App.bridge.get_url_presets();
          if (typeof res === 'string') this.renderBookmarks(res);
        } catch {}
      }
    }
  },

  renderBookmarks(payload) {
    try {
      const arr = typeof payload === 'string' ? JSON.parse(payload) : payload;
      const wrap = document.getElementById('urlBookmarkChips');
      if (!wrap) return;
      wrap.innerHTML = '';
      (arr || []).forEach(url => {
        const chip = document.createElement('div');
        chip.className = 'chip';
        chip.style.cssText = 'display:inline-flex; align-items:center; gap:4px; background:var(--bg-input); border:1px solid var(--border); border-radius:12px; padding:2px 8px; font-size:11px; cursor:pointer;';
        const txt = document.createElement('span');
        txt.textContent = url.length > 40 ? url.slice(0,40)+'…' : url;
        txt.title = url;
        txt.addEventListener('click', () => {
          const inp = document.getElementById('urlBookmarkInput');
          if (inp) inp.value = url;
          this.autoConnectBookmark();
        });
        const del = document.createElement('span');
        del.textContent = '✕';
        del.style.cssText = 'cursor:pointer; color:var(--text-muted); margin-left:4px;';
        del.title = 'Remove';
        del.addEventListener('click', (e) => {
          e.stopPropagation();
          this.removeBookmark(url);
        });
        chip.appendChild(txt);
        chip.appendChild(del);
        wrap.appendChild(chip);
      });
    } catch (e) {
      console.warn('renderBookmarks failed', e);
    }
  },

  addBookmark() {
    const input = document.getElementById('urlBookmarkInput');
    const url = input ? input.value.trim() : '';
    if (!url) return;
    if (App.bridge && App.bridge.add_url_preset) {
      App.bridge.add_url_preset(url);
    }
  },

  removeBookmark(url) {
    if (App.bridge && App.bridge.remove_url_preset) {
      App.bridge.remove_url_preset(url);
    }
  },

  updateUrlRowsConnection() {
    // for each URL in App.state.urls, check if any Chrome tab url matches host/path
    if (!App.state || !App.state.urls) return;
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    // we need to re-render? Instead add data attribute via existing render
    // If tabs list present, we can annotate each row after render
    // Simple: for each url row, find best tab match score
    const rows = tbody.querySelectorAll('tr');
    App.state.urls.forEach((u, idx) => {
      const tr = rows[idx];
      if (!tr) return;
      const connCell = tr.querySelector('.url-conn-status');
      if (!connCell) return;
      const match = this.findBestTabForUrl(u.url);
      if (match) {
        connCell.innerHTML = `<span style="color:var(--success); font-size:11px;" title="${this.esc(match.title)} — ${match.url}">● ${this.esc(match.kind)} (${match.score})</span>`;
        connCell.title = `${match.title} — ${match.url}`;
      } else {
        connCell.innerHTML = `<span style="color:var(--text-muted); font-size:11px;">○ no tab</span>`;
      }
    });
  },

  findBestTabForUrl(url) {
    if (!this.tabs || this.tabs.length === 0) return null;
    // reuse simple scoring similar to python
    const q = url.toLowerCase();
    let best = null;
    let bestScore = -1;
    for (const t of this.tabs) {
      const tabUrl = (t.url || '').toLowerCase();
      let score = 0;
      let kind = 'keyword';
      if (tabUrl === q) { score = 500; kind='url_exact'; }
      else if (tabUrl.startsWith(q) || q.startsWith(tabUrl) ) { score = 300; kind='url_path'; }
      else {
        try {
          const u1 = new URL(url);
          const u2 = new URL(t.url);
          if (u1.host === u2.host) {
            score = 200; kind='host';
            if (u2.pathname && u1.pathname && u2.pathname.includes(u1.pathname.split('/').filter(Boolean).pop() || '')) score += 30;
          }
        } catch {}
        if (score===0) {
          if (tabUrl.includes(q) || q.includes(tabUrl.split('/').pop()||'')) { score=60; kind='keyword'; }
        }
      }
      if (score>bestScore) { bestScore=score; best={...t, score, kind}; }
    }
    return bestScore>0 ? best : null;
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }
};

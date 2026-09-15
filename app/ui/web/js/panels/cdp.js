/* cdp.js — Chrome remote debugging: fetch tabs, match URL to open tab, show connection status per row, pick desired tab — robust with diagnostics */
'use strict';

const CDPPanel = {
  tabs: [],
  connected: false,
  selectedWs: '',
  lastMatchQuery: '',
  _diagnoseBtn: null,

  init() {
    const refreshBtn = document.getElementById('refreshTabsBtn');
    const connectBtn = document.getElementById('connectBtn');
    const tabSelect = document.getElementById('tabSelect');
    const bookmarkInput = document.getElementById('urlBookmarkInput');
    const bookmarkConnectBtn = document.getElementById('urlBookmarkConnectBtn');
    const addBookmarkBtn = document.getElementById('addUrlBookmarkBtn');

    // Add Diagnose button if not exists
    if (connectBtn && !document.getElementById('diagnoseChromeBtn')) {
      const diagBtn = document.createElement('button');
      diagBtn.id = 'diagnoseChromeBtn';
      diagBtn.className = 'btn-small';
      diagBtn.title = 'Diagnose Chrome connection — checks 127.0.0.1:9222, localhost, host.docker.internal';
      diagBtn.innerHTML = '<span class="material-icons" style="font-size:16px;">bug_report</span> Diagnose';
      connectBtn.parentNode.insertBefore(diagBtn, connectBtn.nextSibling);
      this._diagnoseBtn = diagBtn;
      diagBtn.addEventListener('click', () => this.diagnose());
    } else {
      this._diagnoseBtn = document.getElementById('diagnoseChromeBtn');
      if (this._diagnoseBtn) this._diagnoseBtn.addEventListener('click', () => this.diagnose());
    }

    const helpBtn = document.getElementById('chromeHelpBtn');
    if (helpBtn) {
      helpBtn.addEventListener('click', () => {
        const msg = `How to start Chrome for Arena:

1) Close ALL Chrome windows (check Task Manager, end all chrome.exe)
2) Run: start-arena-chrome.bat (in repo root) OR manually:
   "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\\arena-images-chrome"
3) A NEW Chrome window opens with dedicated profile C:\\arena-images-chrome
4) In THAT window, open https://arena.ai and log in
5) In Arena app, click "Diagnose" — you should see ✅ Found X tabs
6) Click "Refresh tabs" — dropdown should list your arena.ai tab
7) Select tab and click "Connect" or use Auto-Connect

If http://127.0.0.1:9222/json/list shows "site can't be reached":
- Port blocked by antivirus/firewall — allow Chrome
- Try different port 9223: chrome.exe --remote-debugging-port=9223 ...
  and change port in Arena settings (future)
- Make sure you used --user-data-dir with NEW folder

Test manually: open http://127.0.0.1:9222 in any browser — should show list of tabs as JSON.`;
        LogConsole.log(msg, 'info');
        alert(msg);
      });
    }

    if (refreshBtn) refreshBtn.addEventListener('click', () => this.fetchTabs());
    if (connectBtn) connectBtn.addEventListener('click', () => this.connectSelected());
    if (tabSelect) tabSelect.addEventListener('change', (e) => {
      this.selectedWs = e.target.value;
    });
    if (bookmarkInput) {
      bookmarkInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') this.autoConnectBookmark();
      });
    }
    if (bookmarkConnectBtn) bookmarkConnectBtn.addEventListener('click', () => this.autoConnectBookmark());
    if (addBookmarkBtn) addBookmarkBtn.addEventListener('click', () => this.addBookmark());

    this.bindBridgeSignals();
    setTimeout(() => this.fetchTabs(), 800);
    setTimeout(() => this.loadBookmarks(), 900);
  },

  bindBridgeSignals() {
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
    const cfg = this.currentConfig || {host:'127.0.0.1', port:9222};
    LogConsole.log(`🔍 Fetching Chrome tabs from http://${cfg.host}:${cfg.port}/json/list … (also tries localhost, host.docker.internal)`, 'info');
    if (App.bridge && App.bridge.get_tabs) {
      try {
        App.bridge.get_tabs((res) => {
          if (res && res !== 'pending') {
            try {
              const tabs = JSON.parse(res);
              if (Array.isArray(tabs)) this.onTabsReceived(res);
            } catch {}
          }
        });
      } catch (e) {
        LogConsole.log('get_tabs failed: ' + e, 'error');
      }
    } else {
      LogConsole.log('Bridge not ready for tabs', 'warn');
    }
  },

  currentConfig: {host:'127.0.0.1', port:9222, user_data_dir:'C:\\arena-images-chrome'},

  updateChromeToolbar(cfg) {
    if (!cfg) return;
    this.currentConfig = cfg;
    const toolbar = document.getElementById('chromeToolbar');
    if (!toolbar) return;
    const codeEl = toolbar.querySelector('code');
    if (codeEl) {
      let cmd = `"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=${cfg.port} --user-data-dir="${cfg.user_data_dir || cfg.user_data_dir}"`;
      if (cfg.extra_args) cmd += ` ${cfg.extra_args}`;
      codeEl.textContent = cmd;
    }
  },

  diagnose() {
    const cfg = this.currentConfig || {host:'127.0.0.1', port:9222};
    LogConsole.log(`🩺 Diagnosing Chrome remote debugging on ${cfg.host}:${cfg.port}… checking 127.0.0.1, localhost, host.docker.internal`, 'info');
    if (App.bridge && App.bridge.diagnose_chrome) {
      App.bridge.diagnose_chrome((res) => {
        try {
          const diag = JSON.parse(res);
          LogConsole.log(diag.summary || 'Diagnose done', diag.summary && diag.summary.includes('✅') ? 'success' : 'warn');
          if (diag.tabs && diag.tabs.length) {
            this.onTabsReceived(JSON.stringify(diag.tabs));
          }
          // show detailed in console as well
          console.log('Chrome diagnose', diag);
          // If no tabs, show help
          if (!diag.tabs || diag.tabs.length === 0) {
            LogConsole.log('💡 FIX for Windows: 1) Close ALL Chrome windows (check Task Manager). 2) Run in CMD: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port=9222 --user-data-dir=\"C:\\arena-images-chrome\" 3) In that NEW Chrome, open https://arena.ai and log in. 4) Click Refresh tabs. 5) If still fails, open http://127.0.0.1:9222/json/list in browser — you should see JSON. If you see \"site can’t be reached\", port is blocked or Chrome didn’t start with flag. 6) Try disabling antivirus, or use port 9223 and change settings.', 'warn');
          }
        } catch (e) {
          LogConsole.log('Diagnose parse failed: ' + e + ' raw: ' + (res||'').slice(0,200), 'error');
        }
      });
    } else {
      LogConsole.log('diagnose_chrome not available', 'error');
    }
  },

  onTabsReceived(payload) {
    try {
      if (payload === 'pending') return;
      const tabs = JSON.parse(payload);
      this.tabs = tabs || [];
      this.renderTabSelect(this.tabs);
      if (this.tabs.length === 0) {
        LogConsole.log('⚠ Received 0 tabs — Chrome running but no pages? Open a page in the dedicated Chrome (C:\\arena-images-chrome) and click Diagnose.', 'warn');
      } else {
        LogConsole.log(`📑 Received ${this.tabs.length} Chrome tabs`, 'success');
      }
      this.updateUrlRowsConnection();
    } catch (e) {
      LogConsole.log('Failed to parse tabs: ' + e + ' payload: ' + (payload||'').slice(0,200), 'error');
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
    if (prev) sel.value = prev;
    const bmInput = document.getElementById('urlBookmarkInput');
    if (bmInput && bmInput.value.trim()) {
      this.highlightMatchingTabs(bmInput.value.trim());
    }
  },

  highlightMatchingTabs(query) {
    if (!query) return;
    const q = query.toLowerCase();
    for (const t of this.tabs) {
      if ((t.url && t.url.toLowerCase().includes(q)) || (t.title && t.title.toLowerCase().includes(q))) {
        LogConsole.log(`💡 Potential match for “${query}”: ${t.title} — ${t.url}`, 'info');
        break;
      }
    }
  },

  connectSelected() {
    const sel = document.getElementById('tabSelect');
    const ws = sel ? sel.value : this.selectedWs;
    if (!ws) {
      LogConsole.log('⚠ No tab selected — click Refresh tabs first, then pick a tab', 'warn');
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
      LogConsole.log('✅ Chrome connected — you can now run jobs', 'success');
    } else if (status === 'disconnected') {
      this.connected = false;
      LogConsole.log('🔌 Chrome disconnected', 'warn');
    } else if (status === 'error') {
      LogConsole.log('❌ Chrome connection error — click Diagnose for details', 'error');
    }
    this.updateUrlRowsConnection();
  },

  _extractUrl(q) {
    if (!q) return '';
    q = q.trim();
    // markdown [text](url) -> extract url inside ()
    let m = q.match(/\(https?:\/\/[^\s\)]+\)/);
    if (m) {
      let inside = m[0].slice(1,-1).trim();
      if (inside.startsWith('http')) return inside;
    }
    // [https://...] or with brackets
    q = q.replace(/^\[+/, '').replace(/\]+$/, '').replace(/^\(+/, '').replace(/\)+$/, '').trim();
    let http = q.match(/(https?:\/\/[^\s\]\)]+)/);
    if (http) return http[1].trim();
    return q;
  },

  autoConnectBookmark() {
    const input = document.getElementById('urlBookmarkInput');
    let query = (input ? input.value.trim() : '').trim();
    if (!query) {
      LogConsole.log('⚠ Bookmark field empty', 'warn');
      return;
    }
    query = this._extractUrl(query);
    LogConsole.log(`🔍 Auto-connect: finding tab for “${query}” …`, 'info');
    this.lastMatchQuery = query;
    if (App.bridge && App.bridge.find_tab_by_url) {
      App.bridge.find_tab_by_url(query);
    }
    if (App.bridge && App.bridge.set_last_url_preset) {
      App.bridge.set_last_url_preset(query);
    }
  },

  onTabMatchResult(query, payload) {
    try {
      const matches = JSON.parse(payload);
      if (!matches || matches.length === 0) {
        LogConsole.log(`❌ No Chrome tab matches “${query}”. Click Diagnose, check Chrome was started with --remote-debugging-port=9222 --user-data-dir="C:\\arena-images-chrome" and that arena.ai page is open in THAT Chrome window (not your normal Chrome).`, 'error');
        // also trigger diagnose automatically
        if (this.tabs.length === 0) {
          LogConsole.log('🩺 Auto-running Diagnose…', 'info');
          setTimeout(() => this.diagnose(), 500);
        }
        return;
      }
      const best = matches[0];
      LogConsole.log(`🎯 Best match (${best.kind}, score ${best.score}): ${best.title} — ${best.url}`, 'success');
      const sel = document.getElementById('tabSelect');
      if (sel) {
        sel.value = best.ws_url;
        this.selectedWs = best.ws_url;
      }
      if (App.bridge && App.bridge.connect_tab) {
        LogConsole.log(`🔗 Auto-connecting to best match: ${best.title}`, 'info');
        App.bridge.connect_tab(best.ws_url);
      }
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
    if (!App.state || !App.state.urls) return;
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    App.state.urls.forEach((u, idx) => {
      const tr = rows[idx];
      if (!tr) return;
      const connCell = tr.querySelector('.url-conn-status');
      if (!connCell) return;
      const match = this.findBestTabForUrl(u.url);
      if (match) {
        connCell.innerHTML = `<span style="color:var(--success, #4ade80); font-size:11px;" title="${this.esc(match.title)} — ${match.url}">● ${this.esc(match.kind)} (${match.score})</span>`;
        connCell.title = `${match.title} — ${match.url}`;
      } else {
        if (this.tabs.length === 0) {
          connCell.innerHTML = `<span style="color:var(--text-muted); font-size:11px;" title="No Chrome tabs — click Diagnose">○ no chrome</span>`;
        } else {
          connCell.innerHTML = `<span style="color:var(--text-muted); font-size:11px;">○ no tab</span>`;
        }
      }
    });
  },

  findBestTabForUrl(url) {
    if (!this.tabs || this.tabs.length === 0) return null;
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

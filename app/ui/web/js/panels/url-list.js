/* url-list.js — URL List panel */
'use strict';

const UrlList = {
  init() {
    const addBtn = document.getElementById('urlAddBtn');
    const input = document.getElementById('urlInput');
    const tableBody = document.getElementById('urlTableBody');
    if (!addBtn || !input || !tableBody) return;

    addBtn.addEventListener('click', () => this.addUrl());
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.addUrl(); });

    tableBody.addEventListener('click', (e) => {
      const chk = e.target.closest('input[type=checkbox]');
      if (chk) {
        const urlId = chk.dataset.urlId;
        const action = chk.dataset.action;
        if (action === 'toggle' && urlId) this.toggleUrl(urlId);
        return;
      }
      const btn = e.target.closest('button');
      if (!btn) return;
      const urlId = btn.dataset.urlId;
      const action = btn.dataset.action;
      if (!urlId || !action) return;
      if (action === 'test') this.testUrl(urlId);
      if (action === 'toggle') this.toggleUrl(urlId);
      if (action === 'remove') this.removeUrl(urlId);
      if (action === 'edit') this.editUrl(urlId);
      if (action === 'connect') this.connectUrl(urlId);
    });
  },

  restore(state) {
    if (!state || !state.urls) return;
    this.render(state.urls);
  },

  render(urls) {
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    urls.forEach(u => {
      const tr = document.createElement('tr');
      tr.dataset.urlId = u.id;
      tr.dataset.url = u.url;
      tr.innerHTML = `
        <td><input type="checkbox" ${u.enabled !== false ? 'checked' : ''} data-action="toggle" data-url-id="${u.id}"></td>
        <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${this.esc(u.url)}">${this.esc(u.url)}</td>
        <td><span class="url-status url-status-${u.status || 'pending'}">${this.esc(u.status || 'pending')}</span></td>
        <td class="url-conn-status" style="font-size:11px;"><span style="color:var(--text-muted);">○ checking…</span></td>
        <td style="font-size:10px; color:var(--text-muted)">${this.esc(u.last_error || '')}</td>
        <td>
          <button class="btn-small" data-action="connect" data-url-id="${u.id}" title="Find Chrome tab matching this URL and connect">Connect</button>
          <button class="btn-small" data-action="test" data-url-id="${u.id}">Test</button>
          <button class="btn-small" data-action="edit" data-url-id="${u.id}">Edit</button>
          <button class="btn-small" data-action="remove" data-url-id="${u.id}">✕</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('urlCount');
    if (countEl) countEl.textContent = `${urls.length} URLs`;
    // update connection status if CDPPanel has tabs
    if (typeof CDPPanel !== 'undefined' && CDPPanel.updateUrlRowsConnection) {
      setTimeout(()=>CDPPanel.updateUrlRowsConnection(), 50);
    }
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  },

  _snapshotUrls() {
    return (App.state && App.state.urls) ? App.state.urls : [];
  },

  addUrl() {
    const input = document.getElementById('urlInput');
    const val = input.value.trim();
    if (!val) return;
    if (App.bridge && App.bridge.add_url) {
      App.bridge.add_url(val, (res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) LogConsole.log('Add URL failed: ' + r.error, 'error');
          else {
            input.value = '';
            LogConsole.log('URL added: ' + val, 'success');
            // record new state for undo
            if (typeof ArenaHistory !== 'undefined') {
              setTimeout(()=>ArenaHistory.recordGlobal('urls', App.state.urls), 100);
            }
          }
        } catch (e) { console.error(e); }
      });
    }
  },

  removeUrl(id) {
    if (App.bridge && App.bridge.remove_url) {
      App.bridge.remove_url(id, () => LogConsole.log('URL removed', 'info'));
    }
  },

  toggleUrl(id) {
    if (App.bridge && App.bridge.toggle_url) {
      App.bridge.toggle_url(id, () => {});
    }
  },

  testUrl(id) {
    if (App.bridge && App.bridge.test_url) {
      LogConsole.log('Testing URL ' + id + '...', 'info');
      App.bridge.test_url(id, (res) => {
        try {
          const r = JSON.parse(res);
          LogConsole.log('Test result: ' + (r.ok ? 'OK' : r.error), r.ok ? 'success' : 'error');
        } catch (e) {}
      });
    }
  },

  editUrl(id) {
    const newUrl = prompt('Edit URL:');
    if (!newUrl) return;
    if (App.bridge && App.bridge.edit_url) {
      App.bridge.edit_url(id, newUrl, (res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok) LogConsole.log('Edit failed: ' + r.error, 'error');
        } catch (e) {}
      });
    }
  },

  _extractUrl(q) {
    if (!q) return '';
    q = q.trim();
    let m = q.match(/\(https?:\/\/[^\s\)]+\)/);
    if (m) {
      let inside = m[0].slice(1,-1).trim();
      if (inside.startsWith('http')) return inside;
    }
    q = q.replace(/^\[+/, '').replace(/\]+$/, '').replace(/^\(+/, '').replace(/\)+$/, '').trim();
    let http = q.match(/(https?:\/\/[^\s\]\)]+)/);
    if (http) return http[1].trim();
    return q;
  },

  connectUrl(id) {
    const urlObj = (App.state && App.state.urls) ? App.state.urls.find(u => u.id === id) : null;
    let url = urlObj ? urlObj.url : '';
    if (!url) { LogConsole.log('⚠ URL not found', 'warn'); return; }
    url = this._extractUrl(url);
    LogConsole.log(`🔍 Connect: finding tab for ${url}`, 'info');
    if (App.bridge && App.bridge.find_tab_by_url) {
      App.bridge.find_tab_by_url(url);
    }
    const inp = document.getElementById('urlBookmarkInput');
    if (inp) inp.value = url;
  }
};

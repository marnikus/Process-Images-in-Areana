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
      const btn = e.target.closest('button');
      if (!btn) return;
      const urlId = btn.dataset.urlId;
      const action = btn.dataset.action;
      if (!urlId || !action) return;
      if (action === 'test') this.testUrl(urlId);
      if (action === 'toggle') this.toggleUrl(urlId);
      if (action === 'remove') this.removeUrl(urlId);
      if (action === 'edit') this.editUrl(urlId);
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
      tr.innerHTML = `
        <td><input type="checkbox" ${u.enabled !== false ? 'checked' : ''} data-action="toggle" data-url-id="${u.id}"></td>
        <td style="max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${this.esc(u.url)}">${this.esc(u.url)}</td>
        <td><span class="url-status url-status-${u.status || 'pending'}">${this.esc(u.status || 'pending')}</span></td>
        <td style="font-size:10px; color:var(--text-muted)">${this.esc(u.last_error || '')}</td>
        <td>
          <button class="btn-small" data-action="test" data-url-id="${u.id}">Test</button>
          <button class="btn-small" data-action="edit" data-url-id="${u.id}">Edit</button>
          <button class="btn-small" data-action="remove" data-url-id="${u.id}">✕</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('urlCount');
    if (countEl) countEl.textContent = `${urls.length} URLs`;
  },

  esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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
  }
};

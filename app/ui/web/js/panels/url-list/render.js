/* url-list/render.js — URL row template + list render. */
'use strict';
window.UrlListRender = {
  _store() { return window.UrlListStore; },
  rowHtml(u) {
    const esc = this._store().esc.bind(this._store());
    return `<td><input type="checkbox" ${u.enabled !== false ? 'checked' : ''} data-action="toggle" data-url-id="${u.id}"></td><td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(u.url)}${u.tab_id ? ' — linked tab ' + esc(u.tab_id) : ''}">${esc(u.url)}<div class="url-job-line" style="font-size:10px; color:var(--warning, #fbbf24);"></div></td><td class="url-tab-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td><td><span class="url-status url-status-${u.status || 'pending'}">${esc(u.status || 'pending')}</span>${u.receiver === false ? `<span class="url-not-receiver" title="${esc(u.receiver_title || 'Not used as job receiver')}">⊘</span>` : ''}</td><td class="url-conn-status" style="font-size:11px;"><span style="color:var(--text-muted);">○ checking…</span></td><td class="url-cool-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td><td class="url-jobs-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td><td style="font-size:10px; color:var(--text-muted)">${esc(u.last_error || '')}</td><td style="white-space:nowrap;"><button class="btn-small" data-action="cool-reset" data-url-id="${u.id}" title="Reset cooldown">♻️</button><button class="btn-small" data-action="connect" data-url-id="${u.id}" title="Find Chrome tab">Connect</button><button class="btn-small url-stop-btn" data-action="stop-job" data-url-id="${u.id}" title="Stop job" disabled>Stop</button><button class="btn-small" data-action="remove" data-url-id="${u.id}">✕</button></td>`;
  },
  render(urls) {
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    urls.forEach(u => {
      const tr = document.createElement('tr');
      tr.dataset.urlId = u.id; tr.dataset.url = u.url; tr.dataset.tabId = u.tab_id || '';
      tr.innerHTML = this.rowHtml(u); tbody.appendChild(tr);
    });
    const countEl = document.getElementById('urlCount');
    if (countEl) countEl.textContent = `${urls.length} URLs`;
    if (typeof CDPPanel !== 'undefined' && CDPPanel.updateUrlRowsConnection) setTimeout(() => CDPPanel.updateUrlRowsConnection(), 50);
    if (window.UrlList?.updateJobLines) window.UrlList.updateJobLines();
    window.UrlListActions?.updateResetAllButton(window.UrlListStore?.poolPages || []);
  },
  fillJobsCell(tr, page) {
    const cell = tr.querySelector('.url-jobs-cell');
    if (!cell) return;
    if (!page) return void (cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>');
    const urlId = tr?.dataset?.urlId || '';
    if (window.UrlListInlineEdit?.isEditing('jobs', urlId)) return;
    const count = String(page.jobs_completed || 0);
    cell.innerHTML = window.UrlListInlineEdit.buttonHtml({ field: 'jobs', value: count, text: count, width: Math.max(2, count.length), urlId, tabId: page.tab_id || '', inputLabel: `Edit jobs completed for ${window.TabLabel?.of(page.tab_id, page) || 'this row'}`, buttonLabel: 'Edit jobs completed', buttonTitle: 'Edit jobs completed' });
  },
  _setTabBtn(btn, tabId) {
    if (!btn) return;
    if (tabId) { btn.dataset.tabId = tabId; btn.disabled = false; btn.style.opacity = ''; }
    else { delete btn.dataset.tabId; btn.disabled = true; btn.style.opacity = '0.4'; }
  },
};

/* url-list/render.js — row + cooldown cells, ≤200 LOC, CC≤10 via helpers */
'use strict';
window.UrlListRender = {
  _store() { return window.UrlListStore; },

  rowHtml(u) {
    const esc = this._store().esc.bind(this._store());
    return `<td><input type="checkbox" ${u.enabled !== false ? 'checked' : ''} data-action="toggle" data-url-id="${u.id}"></td><td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(u.url)}${u.tab_id ? ' — linked tab ' + esc(String(u.tab_id).slice(0,8)) : ''}">${esc(u.url)}<div class="url-job-line" style="font-size:10px; color:var(--warning, #fbbf24);"></div></td><td><span class="url-status url-status-${u.status || 'pending'}">${esc(u.status || 'pending')}</span>${u.receiver === false ? `<span class="url-not-receiver" title="${esc(u.receiver_reason || 'not receiving')}">⊘</span>` : ''}</td><td class="url-conn-status" style="font-size:11px;"><span style="color:var(--text-muted);">○ checking…</span></td><td class="url-cool-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td><td class="url-jobs-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td><td style="font-size:10px; color:var(--text-muted)">${esc(u.last_error || '')}</td><td style="white-space:nowrap;"><button class="btn-small" data-action="cool-reset" data-url-id="${u.id}" title="Reset cooldown">♻️</button><button class="btn-small" data-action="cool-edit" data-url-id="${u.id}" title="Edit cooldown">✎</button><button class="btn-small" data-action="connect" data-url-id="${u.id}" title="Find Chrome tab">Connect</button><button class="btn-small url-stop-btn" data-action="stop-job" data-url-id="${u.id}" title="Stop job" disabled>Stop</button><button class="btn-small" data-action="test" data-url-id="${u.id}">Test</button><button class="btn-small" data-action="edit" data-url-id="${u.id}">Edit</button><button class="btn-small" data-action="remove" data-url-id="${u.id}">✕</button></td>`;
  },

  render(urls) {
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    tbody.innerHTML = '';
    urls.forEach(u => {
      const tr = document.createElement('tr');
      tr.dataset.urlId = u.id;
      tr.dataset.url = u.url;
      tr.dataset.tabId = u.tab_id || '';
      tr.innerHTML = this.rowHtml(u);
      tbody.appendChild(tr);
    });
    const countEl = document.getElementById('urlCount');
    if (countEl) countEl.textContent = `${urls.length} URLs`;
    if (typeof CDPPanel !== 'undefined' && CDPPanel.updateUrlRowsConnection) setTimeout(()=>CDPPanel.updateUrlRowsConnection(), 50);
    if (window.UrlList && window.UrlList.updateJobLines) window.UrlList.updateJobLines();
  },

  fillJobsCell(tr, page) {
    const cell = tr.querySelector('.url-jobs-cell');
    if (!cell) return;
    if (!page) { cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>'; return; }
    cell.innerHTML = `<span title="Jobs completed">${page.jobs_completed || 0}</span>`;
  },

  _setTabBtn(btn, tabId) {
    if (!btn) return;
    if (tabId) { btn.dataset.tabId = tabId; btn.disabled = false; btn.style.opacity = ''; }
    else { delete btn.dataset.tabId; btn.disabled = true; btn.style.opacity = '0.4'; }
  },

  _fmt(s) { return window.PagePoolPanel ? window.PagePoolPanel.fmt(s) : `${s}s`; },

  _badge(page) { return (page.captcha_count||0)>0 ? ` <span title="Captcha detections">🛡x${page.captcha_count}</span>` : ''; },

  _isBusy(page) { return page.status==='busy'||page.status==='waiting_generation'||page.status==='waiting_captcha'; },

  _cooldownHtml(page, badge) {
    const total = page.cooldown_total || 0;
    const of = total>0 ? ` / ${this._fmt(total)}` : '';
    return `<span data-cool-left="${page.cooldown_remaining}" data-cool-at="${Date.now()}" title="${this._store().esc(page.cooldown_reason||'cooling')}">${this._fmt(page.cooldown_remaining)}${of}</span>${badge}`;
  },

  fillCoolCell(tr, page) {
    const cell = tr.querySelector('.url-cool-cell');
    if (!cell) return;
    const resetBtn = tr.querySelector('button[data-action="cool-reset"]');
    const editBtn = tr.querySelector('button[data-action="cool-edit"]');
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>';
      this._setTabBtn(resetBtn, null);
      this._setTabBtn(editBtn, null);
      return;
    }
    this._setTabBtn(resetBtn, page.tab_id);
    this._setTabBtn(editBtn, page.tab_id);
    const badge = this._badge(page);
    if (this._isBusy(page)) { cell.innerHTML = `<span style="color:#4dabf7;" title="Job running">🔵 busy</span>${badge}`; return; }
    if (page.status==='cooldown' && (page.cooldown_remaining||0)>0) { cell.innerHTML = this._cooldownHtml(page, badge); return; }
    if ((page.pending_penalty||0)>0) { cell.innerHTML = `<span title="Captcha penalty pending">+${this._fmt(page.pending_penalty)} pending</span>${badge}`; return; }
    cell.innerHTML = `<span style="color:#4ade80;" title="Ready">✅ ready</span>${badge}`;
  },
};

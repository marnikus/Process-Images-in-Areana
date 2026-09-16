/* url-list.js — URL List panel */
// ideal-size: ~380 lines reason=single UrlList panel object owns row render + pool matching + cooldown/counter cells; splitting the literal would scatter one refresh pass across files that always change together (RULE 18.2)
'use strict';

const UrlList = {
  _lastConnectUrl: '',
  _lastConnectTs: 0,
  init() {
    const addBtn = document.getElementById('urlAddBtn');
    const input = document.getElementById('urlInput');
    const tableBody = document.getElementById('urlTableBody');
    if (!addBtn || !input || !tableBody) return;

    addBtn.addEventListener('click', () => this.addUrl());
    const reparseBtn = document.getElementById('urlReparseBtn');
    if (reparseBtn) reparseBtn.addEventListener('click', () => this.reparseTabs());
    const popupBtn = document.getElementById('urlPopupBtn');
    if (popupBtn) popupBtn.addEventListener('click', () => this.popupTabs());
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.addUrl(); });

    // Job cycle & cooldown controls live on this win (spec correction 2026-09-16)
    const coolSave = document.getElementById('urlCooldownSaveBtn');
    if (coolSave) coolSave.addEventListener('click', () => this.saveCooldownConfig());
    setTimeout(() => this.loadCooldownConfig(), 1400);
    this._coolSnapAt = 0;
    setInterval(() => this.refreshCooldownCells(), 1000);

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
      if (action === 'cool-reset' || action === 'cool-edit') this.coolAction(action, btn);
    });
  },

  reparseTabs() {
    LogConsole.log('🔄 Reparse requested — scanning open tabs…', 'info');
    if (App.bridge && App.bridge.auto_connect_scan) App.bridge.auto_connect_scan('manual');
  },

  popupTabs() {
    if (App.bridge && App.bridge.popup_url_tabs) App.bridge.popup_url_tabs();
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
        <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${this.esc(u.url)}${u.tab_id ? ' — linked tab ' + this.esc(String(u.tab_id).slice(0,8)) : ''}">${this.esc(u.url)}</td>
        <td><span class="url-status url-status-${u.status || 'pending'}">${this.esc(u.status || 'pending')}</span></td>
        <td class="url-conn-status" style="font-size:11px;"><span style="color:var(--text-muted);">○ checking…</span></td>
        <td class="url-cool-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td>
        <td class="url-jobs-cell" style="font-size:11px; white-space:nowrap;"><span style="color:var(--text-muted);">—</span></td>
        <td style="font-size:10px; color:var(--text-muted)">${this.esc(u.last_error || '')}</td>
        <td style="white-space:nowrap;">
          <button class="btn-small" data-action="cool-reset" data-url-id="${u.id}" title="Reset cooldown — tab ready now">♻️</button>
          <button class="btn-small" data-action="cool-edit" data-url-id="${u.id}" title="Edit cooldown timer">✎</button>
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
    const now = Date.now();
    if (url === this._lastConnectUrl && (now - this._lastConnectTs) < 1500) {
      console.debug('UrlList.connectUrl debounced duplicate', url.slice(0,60));
      return;
    }
    this._lastConnectUrl = url;
    this._lastConnectTs = now;
    LogConsole.log(`🔍 Connect: finding tab for ${url}`, 'info');
    if (App.bridge && App.bridge.find_tab_by_url) {
      App.bridge.find_tab_by_url(url);
    }
    const inp = document.getElementById('urlBookmarkInput');
    if (inp) inp.value = url;
  },

  /* ---- Job cycle & cooldown on URL rows (spec 02-04, win-level correction) ---- */

  coolAction(action, btn) {
    const tabId = btn.dataset.tabId;
    if (!tabId) { LogConsole.log('⚠ Tab not in pool — Connect it, then add to pool first', 'warn'); return; }
    if (typeof PagePoolPanel === 'undefined') return;
    if (action === 'cool-reset') PagePoolPanel.resetCooldown(tabId);
    else PagePoolPanel.editCooldown(tabId);
  },

  matchPoolPage(url) {
    if (!url || typeof PagePoolPanel === 'undefined') return null;
    const pages = (PagePoolPanel.snapshot && PagePoolPanel.snapshot.pages) || [];
    if (!pages.length) return null;
    const q = this._extractUrl(url).toLowerCase();
    let hostBest = null;
    for (const p of pages) {
      const pu = (p.url || '').toLowerCase();
      if (!pu) continue;
      if (pu === q) return p;
      if (pu.startsWith(q) || q.startsWith(pu)) return p;
      try {
        if (!hostBest && new URL(p.url).host === new URL(url).host) hostBest = p;
      } catch {}
    }
    return hostBest;
  },

  scorePoolPage(rowUrl, pageUrl) {
    const q = this._extractUrl(rowUrl).toLowerCase();
    const pu = (pageUrl || '').toLowerCase();
    if (!pu || !q) return 0;
    if (pu === q) return 500;
    if (pu.startsWith(q) || q.startsWith(pu)) return 300;
    try {
      if (new URL(pageUrl).host === new URL(rowUrl).host) return 200;
    } catch {}
    return 0;
  },

  assignPoolPages(rows, pages) {
    // Greedy 1:1 — best score first, each page claimed once, so a cooling
    // tab can't hide behind a steady twin with a similar URL. Rows left
    // without a claim fall back to shared best-match (1 tab serves N rows).
    const cands = [];
    rows.forEach((tr, ri) => {
      (pages || []).forEach((p, pi) => {
        const s = this.scorePoolPage(tr.dataset.url || '', p.url);
        if (s > 0) cands.push({ri, pi, s});
      });
    });
    cands.sort((a, b) => b.s - a.s);
    const claimed = new Map(), taken = new Set();
    cands.forEach(c => {
      if (!claimed.has(c.ri) && !taken.has(c.pi)) {
        claimed.set(c.ri, c.pi);
        taken.add(c.pi);
      }
    });
    return claimed;
  },

  matchUnclaimedPage(rowUrl, pages, claimed) {
    // Strict isolation: an unclaimed row may only take an UNCLAIMED page
    // with exact/prefix URL match — never re-render another row's tab, so
    // one job's cooldown can't appear on all rows.
    const taken = new Set((claimed || new Map()).values());
    let best = null, bestScore = 299;
    (pages || []).forEach((p, pi) => {
      if (taken.has(pi)) return;
      const s = this.scorePoolPage(rowUrl, p.url);
      if (s > bestScore) { bestScore = s; best = p; }
    });
    return best;
  },

  refreshCooldownCells() {
    if (typeof PagePoolPanel === 'undefined') return;
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    const snapAt = PagePoolPanel.snapAt || 0;
    if (snapAt && snapAt !== this._coolSnapAt) {
      this._coolSnapAt = snapAt;
      const rows = [...tbody.querySelectorAll('tr')];
      const pages = (PagePoolPanel.snapshot && PagePoolPanel.snapshot.pages) || [];
      const claimed = this.assignPoolPages(rows, pages);
      rows.forEach((tr, ri) => {
        let page = null;
        if (claimed.has(ri)) page = pages[claimed.get(ri)];
        else page = this.matchUnclaimedPage(tr.dataset.url || '', pages, claimed);
        this._fillCoolCell(tr, page);
        this._fillJobsCell(tr, page);
      });
      return;
    }
    tbody.querySelectorAll('.url-cool-cell [data-cool-left]').forEach(el => {
      const base = parseInt(el.getAttribute('data-cool-left') || '0', 10);
      const at = parseInt(el.getAttribute('data-cool-at') || '0', 10);
      const left = Math.max(0, base - Math.floor((Date.now() - at) / 1000));
      const txt = el.textContent;
      const suffix = txt.includes('/') ? txt.slice(txt.indexOf('/')) : '';
      el.textContent = PagePoolPanel.fmt(left) + (suffix ? ' ' + suffix : '');
    });
  },

  _fillJobsCell(tr, page) {
    const cell = tr.querySelector('.url-jobs-cell');
    if (!cell) return;
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool — use Connect, then add to pool">—</span>';
      return;
    }
    const n = page.jobs_completed || 0;
    cell.innerHTML = `<span title="Jobs completed on this tab — next job goes to the free tab with the lowest count">${n}</span>`;
  },

  _fillCoolCell(tr, page) {
    const cell = tr.querySelector('.url-cool-cell');
    if (!cell) return;
    if (typeof page === 'undefined') page = this.matchPoolPage(tr.dataset.url || '');
    const resetBtn = tr.querySelector('button[data-action="cool-reset"]');
    const editBtn = tr.querySelector('button[data-action="cool-edit"]');
    const setTab = (btn, tabId) => {
      if (!btn) return;
      if (tabId) { btn.dataset.tabId = tabId; btn.disabled = false; btn.style.opacity = ''; }
      else { delete btn.dataset.tabId; btn.disabled = true; btn.style.opacity = '0.4'; }
    };
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool — use Connect, then add to pool">—</span>';
      setTab(resetBtn, null); setTab(editBtn, null);
      return;
    }
    setTab(resetBtn, page.tab_id); setTab(editBtn, page.tab_id);
    const fmt = (s) => PagePoolPanel.fmt(s);
    const badge = (page.captcha_count || 0) > 0 ? ` <span title="Captcha detections on this tab">🛡x${page.captcha_count}</span>` : '';
    const busy = page.status === 'busy' || page.status === 'waiting_generation' || page.status === 'waiting_captcha';
    if (busy) {
      cell.innerHTML = `<span style="color:#4dabf7;" title="Job running on this tab">🔵 busy</span>${badge}`;
    } else if (page.status === 'cooldown' && (page.cooldown_remaining || 0) > 0) {
      const total = page.cooldown_total || 0;
      const of = total > 0 ? ` / ${fmt(total)}` : '';
      cell.innerHTML = `<span data-cool-left="${page.cooldown_remaining}" data-cool-at="${Date.now()}" title="${this.esc(page.cooldown_reason || 'cooling')}">${fmt(page.cooldown_remaining)}${of}</span>${badge}`;
    } else if ((page.pending_penalty || 0) > 0) {
      cell.innerHTML = `<span title="Captcha penalty waiting for next cooldown">+${fmt(page.pending_penalty)} pending</span>${badge}`;
    } else {
      cell.innerHTML = `<span style="color:#4ade80;" title="Tab ready for next job">✅ ready</span>${badge}`;
    }
  },

  loadCooldownConfig() {
    if (App.bridge && App.bridge.get_cooldown_config) {
      App.bridge.get_cooldown_config((res) => {
        try {
          const r = JSON.parse(res);
          if (!r.ok || !r.config) return;
          const c = r.config;
          const en = document.getElementById('urlCooldownEnabled');
          if (en) en.checked = c.enabled !== false;
          const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
          setVal('urlCooldownMin', c.min_minutes ?? Math.round((c.min_seconds || 300) / 60));
          setVal('urlCooldownPenalty', c.captcha_penalty_minutes ?? Math.round((c.captcha_penalty_seconds || 900) / 60));
        } catch (e) {}
      });
    }
  },

  saveCooldownConfig() {
    const en = document.getElementById('urlCooldownEnabled');
    const getNum = (id, fb) => { const el = document.getElementById(id); const v = el ? parseFloat(el.value) : NaN; return isNaN(v) ? fb : v; };
    const minM = Math.max(0, Math.min(1440, getNum('urlCooldownMin', 5)));
    const penM = Math.max(0, Math.min(1440, getNum('urlCooldownPenalty', 15)));
    const payload = {enabled: en ? en.checked : true, min_seconds: Math.round(minM * 60), captcha_penalty_seconds: Math.round(penM * 60)};
    if (App.bridge && App.bridge.set_cooldown_config) {
      App.bridge.set_cooldown_config(JSON.stringify(payload), (res) => {
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? `Cooldown saved: ${en && en.checked ? 'on' : 'off'} pause=${minM}m captcha=+${penM}m` : 'Cooldown save failed: ' + r.error, r.ok ? 'success' : 'error');
        } catch (e) {}
      });
    }
  }
};

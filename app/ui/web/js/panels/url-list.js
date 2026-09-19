/* url-list.js — facade C14 ≤200 LOC, delegates to store/render/matching/actions/cooldown */
'use strict';

const UrlList = {
  _store: null,
  _render: null,
  _matching: null,
  _actions: null,
  _cooldown: null,
  _coolSnapAt: 0,
  poolPages: [],

  init() {
    this._store = window.UrlListStore;
    this._render = window.UrlListRender;
    this._matching = window.UrlListMatching;
    this._actions = window.UrlListActions;
    this._cooldown = window.UrlListCooldown;
    const addBtn = document.getElementById('urlAddBtn');
    const input = document.getElementById('urlInput');
    const tableBody = document.getElementById('urlTableBody');
    if (!addBtn || !input || !tableBody) return;
    addBtn.addEventListener('click', () => this.addUrl());
    document.getElementById('urlReparseBtn')?.addEventListener('click', () => this.reparseTabs());
    document.getElementById('urlPopupBtn')?.addEventListener('click', () => this.popupTabs());
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.addUrl(); });
    document.getElementById('urlCooldownSaveBtn')?.addEventListener('click', () => this.saveCooldownConfig());
    setTimeout(() => this.loadCooldownConfig(), 1400);
    setInterval(() => this.refreshCooldownCells(), 1000);
    tableBody.addEventListener('click', (e) => this._handleTableClick(e));
  },

  _handleCheckbox(chk) {
    const urlId = chk.dataset.urlId;
    const action = chk.dataset.action;
    if (action === 'toggle' && urlId) this.toggleUrl(urlId);
  },

  _handleButton(btn) {
    const urlId = btn.dataset.urlId;
    const action = btn.dataset.action;
    if (!urlId || !action) return;
    const map = {
      test: () => this.testUrl(urlId),
      toggle: () => this.toggleUrl(urlId),
      remove: () => this.removeUrl(urlId),
      edit: () => this.editUrl(urlId),
      connect: () => this.connectUrl(urlId),
      'stop-job': () => this.stopJob(urlId),
    };
    if (map[action]) { map[action](); return; }
    if (action === 'cool-reset' || action === 'cool-edit') this.coolAction(action, btn);
  },

  _handleTableClick(e) {
    const chk = e.target.closest('input[type=checkbox]');
    if (chk) { this._handleCheckbox(chk); return; }
    const btn = e.target.closest('button');
    if (!btn) return;
    this._handleButton(btn);
  },

  restore(state) { if (!state || !state.urls) return; this.render(state.urls); },
  render(urls) { if (this._render) this._render.render(urls); },
  esc(s) { return this._store ? this._store.esc(s) : String(s||''); },
  _snapshotUrls() { return this._store ? this._store.snapshotUrls() : []; },
  _extractUrl(q) { return this._store ? this._store.extractUrl(q) : q; },

  addUrl() { return this._actions?.addUrl(); },
  removeUrl(id) { return this._actions?.removeUrl(id); },
  toggleUrl(id) { return this._actions?.toggleUrl(id); },
  testUrl(id) { return this._actions?.testUrl(id); },
  editUrl(id) { return this._actions?.editUrl(id); },
  connectUrl(id) { return this._actions?.connectUrl(id); },
  stopJob(id) { return this._actions?.stopJob(id); },
  coolAction(a,b) { return this._actions?.coolAction(a,b); },
  reparseTabs() { return this._actions?.reparseTabs(); },
  popupTabs() { return this._actions?.popupTabs(); },

  loadCooldownConfig() {
    if (this._cooldown) return this._cooldown.load();
    return this._actions?.loadCooldownConfig();
  },
  saveCooldownConfig() {
    if (this._cooldown) return this._cooldown.save();
    return this._actions?.saveCooldownConfig();
  },

  _delegateMatching(method, ...args) {
    if (this._matching && this._matching[method]) return this._matching[method](...args);
    return null;
  },

  matchPoolPage(url, bound) { return this._delegateMatching('matchPoolPage', url, bound); },
  scorePoolPage(r,p) { return this._delegateMatching('scorePoolPage', r, p) ?? 0; },
  assignPoolPages(rows,pages) { return this._delegateMatching('assignPoolPages', rows, pages) ?? new Map(); },
  matchUnclaimedPage(rowUrl,pages,claimed) { return this._delegateMatching('matchUnclaimedPage', rowUrl, pages, claimed); },
  jobLineForTab(pages,tabId) { return this._delegateMatching('jobLineForTab', pages, tabId) ?? ''; },

  onPoolUpdate(payload) {
    try {
      const snap = JSON.parse(payload);
      this.poolPages = (snap && snap.pages) || [];
      if (this._store) this._store.poolPages = this.poolPages;
    } catch { this.poolPages = []; }
    this.updateJobLines();
  },

  updateJobLines() {
    if (!window.App?.state?.urls) return;
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    const rows = tbody.querySelectorAll('tr');
    window.App.state.urls.forEach((u, idx) => {
      const tr = rows[idx];
      if (!tr) return;
      const line = tr.querySelector('.url-job-line');
      const btn = tr.querySelector('.url-stop-btn');
      const job = this.jobLineForTab(this.poolPages || [], u.tab_id);
      if (line) line.textContent = job;
      if (btn) btn.disabled = !job;
    });
  },

  _refreshFromSnap(rows, pages) {
    const claimed = this.assignPoolPages(rows, pages);
    rows.forEach((tr, ri) => {
      let page = null;
      if (claimed.has(ri)) page = pages[claimed.get(ri)];
      else page = this.matchUnclaimedPage(tr.dataset.url || '', pages, claimed);
      this._fillCoolCell(tr, page);
      this._fillJobsCell(tr, page);
    });
  },

  _tickCooldownCells(tbody) {
    tbody.querySelectorAll('.url-cool-cell [data-cool-left]').forEach(el => {
      const base = parseInt(el.getAttribute('data-cool-left') || '0', 10);
      const at = parseInt(el.getAttribute('data-cool-at') || '0', 10);
      const left = Math.max(0, base - Math.floor((Date.now() - at) / 1000));
      const txt = el.textContent;
      const suffix = txt.includes('/') ? txt.slice(txt.indexOf('/')) : '';
      el.textContent = (window.PagePoolPanel ? window.PagePoolPanel.fmt(left) : `${left}s`) + (suffix ? ' ' + suffix : '');
    });
  },

  refreshCooldownCells() {
    if (typeof PagePoolPanel === 'undefined') return;
    const tbody = document.getElementById('urlTableBody');
    if (!tbody) return;
    const snapAt = PagePoolPanel.snapAt || 0;
    if (snapAt && snapAt !== this._coolSnapAt) {
      this._coolSnapAt = snapAt;
      const rows = [...tbody.querySelectorAll('tr')];
      const pages = (PagePoolPanel.snapshot?.pages) || [];
      this._refreshFromSnap(rows, pages);
      return;
    }
    this._tickCooldownCells(tbody);
  },

  _fillCoolCell(tr, page) { return this._render?.fillCoolCell(tr, page); },
  _fillJobsCell(tr, page) { return this._render?.fillJobsCell(tr, page); },
};

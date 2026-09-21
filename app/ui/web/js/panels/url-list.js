/* url-list.js — facade C14 ≤200 LOC, delegates to store/render/matching/actions/cooldown/listeners.
   2026-10-02: DOM listeners live in url-list/listeners.js (bound once via Boot.bindOnce);
   the facade never calls addEventListener itself. */
'use strict';

const UrlList = {
  _store: null,
  _render: null,
  _matching: null,
  _actions: null,
  _cooldown: null,
  _listeners: null,
  _cells: null,
  _timersStarted: false,
  _coolSnapAt: 0,
  poolPages: [],

  init() {
    this._store = window.UrlListStore;
    this._render = window.UrlListRender;
    this._matching = window.UrlListMatching;
    this._actions = window.UrlListActions;
    this._cooldown = window.UrlListCooldown;
    this._listeners = window.UrlListListeners;
    this._cells = window.UrlListCells;
    if (!this._listeners || !this._listeners.bind(this)) return;
    if (this._timersStarted) return;
    this._timersStarted = true;
    setTimeout(() => this.loadCooldownConfig(), 1400);
    setInterval(() => this.refreshCooldownCells(), 1000);
  },

  _handleTableClick(e) { return this._listeners?.onTableClick(this, e); },

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
      this._fillTabCell(tr, page);
      this._fillCoolCell(tr, page);
      this._fillJobsCell(tr, page);
    });
  },

  /* D-4: the same element-anchored tick as the pool table, floored at 00:00. */
  _tickCooldownCells(tbody) { return this._cells && this._cells.tick(tbody); },

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

  _fillTabCell(tr, page) { return this._cells?.fillTabCell(tr, page); },
  _fillCoolCell(tr, page) { return this._cells?.fillCoolCell(tr, page); },
  _fillJobsCell(tr, page) { return this._render?.fillJobsCell(tr, page); },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.UrlList = UrlList;

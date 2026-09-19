/* url-list.js — facade C13 split into store/render/matching/actions, RULE18 file 150-300, CC≤10 */
'use strict';

const UrlList = {
  _store: null,
  _render: null,
  _matching: null,
  _actions: null,
  _coolSnapAt: 0,
  poolPages: [],

  get _lastConnectUrl() { return this._store ? this._store._lastConnectUrl : ''; },
  set _lastConnectUrl(v) { if (this._store) this._store._lastConnectUrl = v; },
  get _lastConnectTs() { return this._store ? this._store._lastConnectTs : 0; },
  set _lastConnectTs(v) { if (this._store) this._store._lastConnectTs = v; },

  init() {
    this._store = window.UrlListStore;
    this._render = window.UrlListRender;
    this._matching = window.UrlListMatching;
    this._actions = window.UrlListActions;
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
  render(urls) { this._render.render(urls); },
  esc(s) { return this._store.esc(s); },
  _snapshotUrls() { return this._store.snapshotUrls(); },
  _extractUrl(q) { return this._store.extractUrl(q); },

  addUrl() { if (this._actions && this._actions.addUrl) return this._actions.addUrl(); },
  removeUrl(id) { if (this._actions && this._actions.removeUrl) return this._actions.removeUrl(id); },
  toggleUrl(id) { if (this._actions && this._actions.toggleUrl) return this._actions.toggleUrl(id); },
  testUrl(id) { if (this._actions && this._actions.testUrl) return this._actions.testUrl(id); },
  editUrl(id) { if (this._actions && this._actions.editUrl) return this._actions.editUrl(id); },
  connectUrl(id) { if (this._actions && this._actions.connectUrl) return this._actions.connectUrl(id); },
  stopJob(id) { if (this._actions && this._actions.stopJob) return this._actions.stopJob(id); },
  coolAction(a,b) { if (this._actions && this._actions.coolAction) return this._actions.coolAction(a,b); },
  reparseTabs() { if (this._actions && this._actions.reparseTabs) return this._actions.reparseTabs(); },
  popupTabs() { if (this._actions && this._actions.popupTabs) return this._actions.popupTabs(); },
  _applyCooldownConfig(c) {
    const en = document.getElementById('urlCooldownEnabled');
    if (en) en.checked = c.enabled !== false;
    const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    setVal('urlCooldownMin', c.min_minutes ?? Math.round((c.min_seconds||300)/60));
    setVal('urlCooldownPenalty', c.captcha_penalty_minutes ?? Math.round((c.captcha_penalty_seconds||900)/60));
    setVal('urlCooldownRateLimit', c.rate_limit_penalty_minutes ?? Math.round((c.rate_limit_penalty_seconds||1800)/60));
  },

  _readCooldownInputs() {
    const en = document.getElementById('urlCooldownEnabled');
    const getNum = (id, fb) => { const el = document.getElementById(id); const v = el ? parseFloat(el.value) : NaN; return isNaN(v) ? fb : v; };
    const minM = Math.max(0, Math.min(1440, getNum('urlCooldownMin',5)));
    const penM = Math.max(0, Math.min(1440, getNum('urlCooldownPenalty',15)));
    const rlM = Math.max(0, Math.min(1440, getNum('urlCooldownRateLimit',30)));
    return { en, minM, penM, rlM };
  },

  loadCooldownConfig() {
    if (this._actions && this._actions.loadCooldownConfig) return this._actions.loadCooldownConfig();
    const b = window.App && window.App.bridge;
    if (!b || !b.get_cooldown_config) return;
    b.get_cooldown_config((res)=>{
      try {
        const r=JSON.parse(res);
        if (!r.ok||!r.config) return;
        this._applyCooldownConfig(r.config);
      } catch {}
    });
  },

  saveCooldownConfig() {
    if (this._actions && this._actions.saveCooldownConfig) return this._actions.saveCooldownConfig();
    const inputs = this._readCooldownInputs();
    const payload = { enabled: inputs.en?inputs.en.checked:true, min_seconds:Math.round(inputs.minM*60), captcha_penalty_seconds:Math.round(inputs.penM*60), rate_limit_penalty_seconds:Math.round(inputs.rlM*60) };
    const b = window.App && window.App.bridge;
    if (b && b.set_cooldown_config) b.set_cooldown_config(JSON.stringify(payload),(res)=>{
      try {
        const r=JSON.parse(res);
        const msg = r.ok ? `Cooldown saved: ${inputs.en&&inputs.en.checked?'on':'off'} pause=${inputs.minM}m captcha=+${inputs.penM}m limit=+${inputs.rlM}m` : 'Cooldown save failed: '+r.error;
        if (typeof LogConsole !== 'undefined') LogConsole.log(msg, r.ok?'success':'error');
      } catch {}
    });
  },

  _findBound(boundTabId, pages) {
    if (!boundTabId) return null;
    return (pages||[]).find(p => p && p.tab_id === boundTabId) || null;
  },

  _extractForScore(q) {
    try {
      if (this._store && this._store.extractUrl) return this._store.extractUrl(q).toLowerCase();
    } catch {}
    return (q||'').toLowerCase();
  },

  _findExactPrefix(q, pages) {
    for (const p of pages) {
      const pu = (p.url||'').toLowerCase();
      if (!pu) continue;
      if (pu===q || pu.startsWith(q) || q.startsWith(pu)) return p;
    }
    return null;
  },

  _findHostMatch(url, pages) {
    try {
      const host = new URL(url).host;
      for (const p of pages) {
        try { if (p.url && new URL(p.url).host===host) return p; } catch {}
      }
    } catch {}
    return null;
  },

  _pagesSnapshot() {
    if (typeof PagePoolPanel !== 'undefined' && PagePoolPanel.snapshot && PagePoolPanel.snapshot.pages) return PagePoolPanel.snapshot.pages;
    return [];
  },

  matchPoolPage(url, bound) {
    if (this._matching && this._matching.matchPoolPage) return this._matching.matchPoolPage(url, bound);
    if (!url) return null;
    const pages = this._pagesSnapshot();
    if (!pages.length) return null;
    const b = this._findBound(bound, pages);
    if (b) return b;
    const q = this._extractForScore(url);
    const exact = this._findExactPrefix(q, pages);
    if (exact) return exact;
    return this._findHostMatch(url, pages);
  },

  scorePoolPage(r,p) {
    if (this._matching && this._matching.scorePoolPage) return this._matching.scorePoolPage(r,p);
    const q = this._extractForScore(r);
    const pu = (p||'').toLowerCase();
    if (!pu||!q) return 0;
    if (pu===q) return 500;
    if (pu.startsWith(q)||q.startsWith(pu)) return 300;
    try { if (new URL(p).host === new URL(r).host) return 200; } catch {}
    return 0;
  },

  _claimBound(rows,pages,claimed,taken) {
    rows.forEach((tr, ri) => {
      const bound = tr.dataset ? (tr.dataset.tabId || '') : '';
      if (!bound) return;
      const pi = (pages||[]).findIndex(p => p && p.tab_id === bound);
      if (pi>=0 && !taken.has(pi)) { claimed.set(ri, pi); taken.add(pi); }
    });
  },

  _buildCandidates(rows,pages) {
    const cands=[];
    rows.forEach((tr, ri) => {
      (pages||[]).forEach((p, pi) => {
        const s = this.scorePoolPage(tr.dataset.url||'', p.url);
        if (s>0) cands.push({ri, pi, s});
      });
    });
    cands.sort((a,b)=>b.s-a.s);
    return cands;
  },

  assignPoolPages(rows,pages) {
    if (this._matching && this._matching.assignPoolPages) return this._matching.assignPoolPages(rows,pages);
    const claimed = new Map(), taken = new Set();
    this._claimBound(rows,pages,claimed,taken);
    const cands = this._buildCandidates(rows,pages);
    cands.forEach(c => {
      if (!claimed.has(c.ri) && !taken.has(c.pi)) { claimed.set(c.ri, c.pi); taken.add(c.pi); }
    });
    return claimed;
  },

  matchUnclaimedPage(rowUrl,pages,claimed) {
    if (this._matching && this._matching.matchUnclaimedPage) return this._matching.matchUnclaimedPage(rowUrl,pages,claimed);
    const taken = new Set((claimed||new Map()).values());
    let best=null, bestScore=299;
    (pages||[]).forEach((p, pi) => {
      if (taken.has(pi)) return;
      const s = this.scorePoolPage(rowUrl, p.url);
      if (s>bestScore) { bestScore=s; best=p; }
    });
    return best;
  },
  jobLineForTab(pages,tabId) {
    if (this._matching && this._matching.jobLineForTab) return this._matching.jobLineForTab(pages,tabId);
    if (!tabId) return '';
    const p = (pages||[]).find(x=>x&&x.tab_id===tabId);
    const name = p ? (p.current_image||'') : '';
    return name ? `\u25b6 ${name}` : '';
  },

  onPoolUpdate(payload) {
    try {
      const snap = JSON.parse(payload);
      this.poolPages = (snap && snap.pages) || [];
      if (this._store) this._store.poolPages = this.poolPages;
    } catch { this.poolPages = []; }
    this.updateJobLines();
  },

  updateJobLines() {
    if (!window.App || !window.App.state || !window.App.state.urls) return;
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
      el.textContent = window.PagePoolPanel.fmt(left) + (suffix ? ' ' + suffix : '');
    });
  },

  _fillCoolCell(tr, page) {
    if (this._render && this._render.fillCoolCell) return this._render.fillCoolCell(tr, page);
    const cell = tr.querySelector('.url-cool-cell');
    if (!cell) return;
    if (!page) { cell.innerHTML = '<span>—</span>'; return; }
    cell.innerHTML = `<span>${page.jobs_completed||0}</span>`;
  },
  _fillJobsCell(tr, page) {
    if (this._render && this._render.fillJobsCell) return this._render.fillJobsCell(tr, page);
    const cell = tr.querySelector('.url-jobs-cell');
    if (!cell) return;
    if (!page) { cell.innerHTML = '<span>—</span>'; return; }
    cell.innerHTML = `<span>${page.jobs_completed||0}</span>`;
  },
};

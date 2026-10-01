/* url-list/cells.js — the URL row's Tab + Cooldown cells, ≤120 LOC, CC≤10.
   Extracted from render.js (2026-09-21, D-4/D-7) so the row-template file keeps
   its frozen size and the countdown rule lives in one place: a live timer wins
   over every status label, a debt is named a debt, a ready row reads 00:00. */
'use strict';
const UrlListCells = {
  _store() { return window.UrlListStore; },
  _fmt(s) { return window.PagePoolPanel ? window.PagePoolPanel.fmt(s) : `${s}s`; },

  _badge(page) {
    return (page.captcha_count || 0) > 0
      ? ` <span title="Captcha detections">🛡x${page.captcha_count}</span>` : '';
  },

  _isBusy(page) {
    return page.status === 'busy' || page.status === 'waiting_generation'
      || page.status === 'waiting_captcha';
  },

  _tabLabel(page) { return window.TabLabel.of(page.tab_id, page); },

  fillTabCell(tr, page) {
    const cell = tr.querySelector('.url-tab-cell');
    if (!cell) return;
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>';
      return;
    }
    const esc = this._store().esc.bind(this._store()), no = Number(page.worker_no) > 0 ? `<b class="worker-no">#${Number(page.worker_no)}</b> ` : '';  // Page Pool's #N
    cell.innerHTML = `<span title="${esc(page.tab_id)}">${no}${page.browser === 'firefox' ? '🦊 ' : '🌐 '}${esc(this._tabLabel(page))}</span>`;
  },

  _setTabBtn(btn, tabId) {
    if (!btn) return;
    if (tabId) { btn.dataset.tabId = tabId; btn.disabled = false; btn.style.opacity = ''; }
    else { delete btn.dataset.tabId; btn.disabled = true; btn.style.opacity = '0.4'; }
  },

  _clockHtml(page, urlId) {
    return window.UrlListInlineEdit.cooldownHtml(page, urlId, this._fmt.bind(this));
  },

  _busyHtml(page, left) {
    if (left > 0 || !this._isBusy(page)) return '';
    return '<span style="color:#4dabf7;" title="Job running">🔵 busy</span> ';
  },

  _debtHtml(pending) {
    return ` <span title="Stacked penalty — starts cooling when this job ends">+${this._fmt(pending)} debt</span>`;
  },

  fillCoolCell(tr, page) {
    const cell = tr.querySelector('.url-cool-cell');
    if (!cell) return;
    const resetBtn = tr.querySelector('button[data-action="cool-reset"]');
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>';
      this._setTabBtn(resetBtn, null);
      return;
    }
    this._setTabBtn(resetBtn, page.tab_id);
    const left = page.cooldown_remaining || 0, pending = page.pending_penalty || 0;
    cell.innerHTML = this._busyHtml(page, left) + this._clockHtml(page, tr.dataset.urlId)
      + (pending > 0 ? this._debtHtml(pending) : '') + this._badge(page);
  },

  /* Clock edits and ticks share the inline button's anchored time values. */
  tick(root) { return window.UrlListInlineEdit.tick(root, this._fmt.bind(this)); },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.UrlListCells = UrlListCells;

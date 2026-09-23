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
    const esc = this._store().esc.bind(this._store());
    cell.innerHTML = `<span title="${esc(page.tab_id)}">${esc(this._tabLabel(page))}</span>`;
  },

  _setTabBtn(btn, tabId) {
    if (!btn) return;
    if (tabId) { btn.dataset.tabId = tabId; btn.disabled = false; btn.style.opacity = ''; }
    else { delete btn.dataset.tabId; btn.disabled = true; btn.style.opacity = '0.4'; }
  },

  _clockHtml(page) {
    const left = page.cooldown_remaining || 0;
    const total = page.cooldown_total || 0;
    const of = (left > 0 && total > 0) ? ` / ${this._fmt(total)}` : '';
    const title = this._store().esc(page.cooldown_reason || (left > 0 ? 'cooling' : 'no active timer'));
    return `<span data-cool-tab="${this._store().esc(page.tab_id)}" data-cool-left="${left}" data-cool-at="${Date.now()}" title="${title}">${this._fmt(left)}${of}</span>`;
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
    const editBtn = tr.querySelector('button[data-action="cool-edit"]');
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>';
      this._setTabBtn(resetBtn, null);
      this._setTabBtn(editBtn, null);
      return;
    }
    this._setTabBtn(resetBtn, page.tab_id);
    this._setTabBtn(editBtn, page.tab_id);
    const left = page.cooldown_remaining || 0;
    const pending = page.pending_penalty || 0;
    cell.innerHTML = this._busyHtml(page, left) + this._clockHtml(page)
      + (pending > 0 ? this._debtHtml(pending) : '') + this._badge(page);
  },

  /* Element-anchored tick: each clock carries its own `data-cool-at`, and 00:00
     is a hard floor — the value only ever counts down. */
  tick(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('.url-cool-cell [data-cool-left]').forEach(el => {
      const base = parseInt(el.getAttribute('data-cool-left') || '0', 10);
      const at = parseInt(el.getAttribute('data-cool-at') || '0', 10);
      const left = Math.max(0, base - Math.floor((Date.now() - at) / 1000));
      const txt = el.textContent;
      el.textContent = left <= 0 ? this._fmt(0)
        : this._fmt(left) + (txt.includes('/') ? ' ' + txt.slice(txt.indexOf('/')) : '');
    });
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.UrlListCells = UrlListCells;

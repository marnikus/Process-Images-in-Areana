/* url-list/cells.js — URL row Tab + Cooldown cells. */
'use strict';
const UrlListCells = {
  _store() { return window.UrlListStore; },
  _fmt(s) { return window.PagePoolPanel ? window.PagePoolPanel.fmt(s) : `${s}s`; },
  _badge(page) { return (page.captcha_count || 0) > 0 ? ` <span title="Captcha detections">🛡x${page.captcha_count}</span>` : ''; },
  _isBusy(page) { return page.status === 'busy' || page.status === 'waiting_generation' || page.status === 'waiting_captcha'; },
  _tabLabel(page) { return window.TabLabel.of(page.tab_id, page); },
  fillTabCell(tr, page) {
    const cell = tr.querySelector('.url-tab-cell');
    if (!cell) return;
    if (!page) return void (cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>');
    const esc = this._store().esc.bind(this._store()), no = Number(page.worker_no) > 0 ? `<b class="worker-no">#${Number(page.worker_no)}</b> ` : '';
    cell.innerHTML = `<span title="${esc(page.tab_id)}">${no}${page.browser === 'firefox' ? '🦊 ' : '🌐 '}${esc(this._tabLabel(page))}</span>`;
  },
  _setTabBtn(btn, tabId) {
    if (!btn) return;
    if (tabId) { btn.dataset.tabId = tabId; btn.disabled = false; btn.style.opacity = ''; }
    else { delete btn.dataset.tabId; btn.disabled = true; btn.style.opacity = '0.4'; }
  },
  _clockMeta(page, left) {
    const title = page.cooldown_reason || (left > 0 ? 'cooling' : 'no active timer');
    const named = window.TabLabel ? window.TabLabel.of(page.tab_id, page) : '';
    return { label: named || 'this row', title, tabId: page.tab_id ? page.tab_id : '' };
  },
  _clockHtml(tr, page) {
    let left = Number(page.cooldown_remaining), total = Number(page.cooldown_total);
    if (!Number.isFinite(left)) left = 0;
    if (!Number.isFinite(total)) total = 0;
    const txt = this._fmt(left), meta = this._clockMeta(page, left);
    const spec = { field: 'cooldown', value: txt, text: txt, width: Math.max(5, txt.length), urlId: tr.dataset.urlId || '', tabId: meta.tabId, inputLabel: `Edit cooldown for ${meta.label}`, buttonLabel: 'Edit cooldown', buttonTitle: meta.title };
    const html = window.UrlListInlineEdit.buttonHtml(spec).replace('<button ', `<button data-cool-tab="${this._store().esc(page.tab_id)}" data-cool-left="${left}" data-cool-at="${Date.now()}" `);
    if (left <= 0 || total <= 0) return html;
    return html + ` <span class="url-cool-total">/ ${this._fmt(total)}</span>`;
  },
  _busyHtml(page, left) { return left > 0 || !this._isBusy(page) ? '' : '<span style="color:#4dabf7;" title="Job running">🔵 busy</span> '; },
  fillCoolCell(tr, page) {
    const cell = tr.querySelector('.url-cool-cell');
    if (!cell) return;
    const resetBtn = tr.querySelector('button[data-action="cool-reset"]');
    if (!page) {
      cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>';
      return void this._setTabBtn(resetBtn, null);
    }
    this._setTabBtn(resetBtn, page.tab_id);
    if (window.UrlListInlineEdit?.isEditing('cooldown', tr.dataset.urlId)) return;
    const left = Number(page.cooldown_remaining) || 0, pending = Number(page.pending_penalty) || 0;
    const debt = pending > 0 ? ` <span title="Stacked penalty — starts cooling when this job ends">+${this._fmt(pending)} debt</span>` : '';
    cell.innerHTML = this._busyHtml(page, left) + this._clockHtml(tr, page) + debt + this._badge(page);
  },
  tick(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('.url-cool-cell [data-cool-left]').forEach(el => {
      const base = parseInt(el.getAttribute('data-cool-left') || '0', 10), at = parseInt(el.getAttribute('data-cool-at') || '0', 10);
      const left = Math.max(0, base - Math.floor((Date.now() - at) / 1000)), txt = el.textContent;
      if (left <= 0) { el.textContent = this._fmt(0); return; }
      el.textContent = this._fmt(left) + (txt.includes('/') ? ' ' + txt.slice(txt.indexOf('/')) : '');
    });
  },
};
if (typeof window !== 'undefined') window.UrlListCells = UrlListCells;

/* job-history/render.js — string builders for the history table.
   Pool-table look (the shared queue-table class): one row per finished job,
   newest first; every long value is truncated in the cell with the full text
   in the title tooltip. */
'use strict';
window.JobHistoryRender = {
  _store() { return window.JobHistoryStore; },

  esc(s) {
    return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  },

  _short(s, n) {
    const t = String(s == null ? '' : s);
    return t.length > n ? t.slice(0, n - 1) + '…' : t;
  },

  _statusCell(e) {
    const ok = e.status === 'completed';
    const cls = ok ? 'history-status-ok' : 'history-status-err';
    const mark = ok ? '✓' : '✗';
    return `<span class="${cls}">${mark} ${this.esc(e.status || (ok ? 'completed' : 'failed'))}</span>`;
  },

  _errorCell(e) {
    if (!e.error) return '<span class="history-dim">—</span>';
    return `<span class="history-err" title="${this.esc(e.error)}">${this.esc(this._short(e.error, 60))}</span>`;
  },

  _imageCell(e) {
    const id = this.esc(e.image_id || '');
    const name = this.esc(e.image || '');
    const full = this.esc(e.image_path || e.image || '');
    return `<span class="history-imgcell"><img class="history-thumb" data-img-id="${id}" alt="" title="${full}"><span title="${full}">${name}</span></span>`;
  },

  _folderCell(e) {
    if (!e.folder) return '<span class="history-dim">—</span>';
    const full = this.esc(e.folder);
    return `<span class="history-pathcell"><span title="${full}">${this.esc(this._short(e.folder, 40))}</span>`
      + `<button class="btn-small" title="Open in Explorer" data-act="reveal" data-path="${full}">📁</button></span>`;
  },

  _linkCell(e) {
    if (e.status !== 'completed' || !e.output_path) return '<span class="history-dim">—</span>';
    const full = this.esc(e.output_path);
    const base = this.esc(String(e.output_path).split(/[/\\]/).pop());
    return `<span class="history-pathcell"><a href="file://${full}" title="${full}">${base}</a>`
      + `<button class="btn-small" title="Copy path" data-act="copy" data-path="${full}">📋</button></span>`;
  },

  _timeCell(iso) {
    if (!iso) return '<span class="history-dim">—</span>';
    const t = String(iso);
    const hm = t.length >= 19 ? t.slice(11, 19) : t;
    return `<span title="${this.esc(t)}" class="history-time">${this.esc(hm)}</span>`;
  },

  _captchaCell(e) {
    const n = Number(e.captcha) || 0;
    if (n <= 0) return '<span class="history-dim">—</span>';
    return `<span class="history-captcha" title="${n} captcha encounter${n === 1 ? '' : 's'} during this job">🛡 ×${n}</span>`;
  },

  /* The readable `{email}_{4 digits}` handle (D-7). The row froze its label at
     record time, so a finished job keeps the name it ran under even after the
     tab closed; a row written before labels existed falls back to the live
     lookup, then to the short id. The full hex stays in the tooltip. */
  _tabCell(e) {
    const id = String(e.tab_id || '');
    const live = window.TabLabel ? window.TabLabel.of(id) : '';
    /* A real handle (frozen at record time, else the live pool lookup); the
       short id is only a fallback, so it never pollutes the tooltip. */
    const alias = e.tab_label || (live && live !== id.slice(0, 8) ? live : '');
    const title = alias ? `${alias} · ${id}` : id;
    return `<td title="${this.esc(title)}">${this.esc(this._short(alias || id.slice(0, 8), 30))}</td>`;
  },

  _row(e) {
    return '<tr>'
      + this._tabCell(e)
      + `<td>${this.esc(e.worker_no === '' || e.worker_no == null ? '—' : '#' + e.worker_no)}</td>`
      + `<td><b>${this.esc(e.job_no == null ? '' : e.job_no)}</b></td>`
      + `<td>${this._statusCell(e)}</td>`
      + `<td>${this._errorCell(e)}</td>`
      + `<td>${this._imageCell(e)}</td>`
      + `<td>${this._folderCell(e)}</td>`
      + `<td>${this._linkCell(e)}</td>`
      + `<td>${this._timeCell(e.started)}</td>`
      + `<td>${this._timeCell(e.finished)}</td>`
      + `<td>${this._captchaCell(e)}</td>`
      + '</tr>';
  },

  rows() {
    const list = this._store().entries || [];
    if (!list.length) return '<tr><td colspan="11" class="history-empty">no finished jobs yet — run the queue and they land here</td></tr>';
    return list.map((e) => this._row(e)).join('');
  },

  countText() {
    const st = this._store();
    const shown = (st.entries || []).length;
    return `${shown} shown · ${st.total} stored`;
  },
};

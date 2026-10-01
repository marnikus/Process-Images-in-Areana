/* url-list/reset.js — row working state, Stop, and per-row cooldown reset.

   2026-09-21 (D-7): derive the status/job line from the row's pool page so busy
   tabs remain visible and stoppable. Python owns reset decisions; this module
   calls the canonical row-reset slot and reports its reply. */
'use strict';
const UrlListReset = {
  FLASH_MS: 1200,
  _store() { return window.UrlListStore; },
  _bridge() { return window.App && window.App.bridge; },

  isBusy(page) {
    return !!page && (page.status === 'busy' || page.status === 'waiting_generation'
      || page.status === 'waiting_captcha');
  },

  /** Working state of the pooled page a row owns: '' = row owns no tab (keep the
      validation status), else processing > cooldown > ready > the raw status. */
  stateLabel(page) {
    if (!page) return '';
    if (this.isBusy(page)) return 'processing';
    if ((page.cooldown_remaining || 0) > 0) return 'cooldown';
    return page.status === 'steady' ? 'ready' : (page.status || '');
  },

  /** The row's own CDP validation status — what the pill shows when no pooled
      tab is claimed by this row (so URL feedback is never lost, D-7). */
  rowStatus(tr) {
    const id = tr && tr.dataset ? tr.dataset.urlId : null;
    const u = this._store().snapshotUrls().find(x => String(x.id) === String(id));
    return (u && u.status) || '';
  },

  fillStatusCell(tr, page) {
    const cell = tr && tr.querySelector ? tr.querySelector('.url-status') : null;
    if (!cell) return false;
    const label = this.stateLabel(page) || this.rowStatus(tr);
    if (!label) return false;                    // nothing known: leave the pill alone
    cell.className = `url-status url-status-${label}`;
    cell.textContent = label;
    cell.title = page ? `Tab state from the pool: ${label}` : label;
    return true;
  },

  _pageOf(pages, tabId) {
    return (pages || []).find(p => p && p.tab_id === tabId) || null;
  },

  /** Job line of a tab: the running image, else `⏳ busy` for a busy tab whose
      image was lost — so the Stop button is never dead while a job runs (F-5). */
  jobLine(pages, tabId) {
    if (!tabId) return '';
    const line = window.UrlListMatching ? window.UrlListMatching.jobLineForTab(pages, tabId) : '';
    if (line) return line;
    return this.isBusy(this._pageOf(pages, tabId)) ? '⏳ busy' : '';
  },

  _tabOf(urlId) {
    const u = this._store().snapshotUrls().find(x => String(x.id) === String(urlId));
    return (u && u.tab_id) || null;
  },

  _label(tab) { return window.TabLabel ? window.TabLabel.of(tab) : tab; },
  _fmt(s) { return window.PagePoolPanel ? window.PagePoolPanel.fmt(s) : `${s}s`; },
  _parse(res) { try { return typeof res === 'string' ? JSON.parse(res) : res; } catch { return null; } },

  /* ---- Stop: abort a live job, or repair a tab no run owns (D-3) ---- */

  stopJob(urlId) {
    const tab = this._tabOf(urlId);
    if (!tab) { LogConsole.log('Stop: row has no linked tab yet', 'warn'); return; }
    const b = this._bridge();
    if (b && b.stop_tab_job) b.stop_tab_job(tab, (res) => this._onStop(tab, res));
  },

  _onStop(tab, res) {
    const r = this._parse(res);
    if (!r || !r.ok) { LogConsole.log('Stop: ' + ((r && r.error) || 'failed'), 'error'); return; }
    if (r.mode === 'abort') {
      LogConsole.log(`⛔ Stop requested for tab ${this._label(tab)} — job aborts, then cooldown`, 'warn');
      return;
    }
    LogConsole.log(`♻️ Stop: tab ${this._label(tab)} reset — cooldown ${this._fmt(r.seconds || 0)}`, 'success');
  },

  /* ---- Clear time: the countdown goes, visibly (D-5) ---- */

  clearTime(urlId, row) {
    const tab = this._tabOf(urlId);
    if (!tab) { LogConsole.log('Clear time: row has no linked tab yet', 'warn'); return; }
    const b = this._bridge(), target = row || this._rowOf(urlId);
    if (!b || typeof b.reset_page_cooldown !== 'function') {
      LogConsole.log('Clear time: bridge unavailable', 'error');
      return;
    }
    window.UrlListInlineEdit?.showClearedTime(target);
    try { b.reset_page_cooldown(tab, (res) => this._onClear(tab, urlId, target, res)); }
    catch (error) { this._onClear(tab, urlId, target, { ok: false, error: String(error) }); }
  },

  _onClear(tab, urlId, row, res) {
    const r = this._parse(res);
    if (!r?.ok) {
      LogConsole.log('Clear time: ' + (r?.error || 'failed'), 'error');
      window.PagePoolPanel?.refresh?.();
      return;
    }
    const target = row || this._rowOf(urlId), was = this._fmt(r.was ?? 0);
    if (r.busy) return LogConsole.log(`⏳ Clear time: tab ${this._label(tab)} still busy — ${was} removed, the job keeps its page`, 'warn');
    LogConsole.log(`♻️ Clear time: tab ${this._label(tab)} ready now — ${was} removed${r.job_cleared ? ' (stale job cleared)' : ''}`, 'success');
    this.flashCleared(target);
  },

  /** Green blink on the cool cell: the user asked for a visible confirmation. */
  flashCleared(row) {
    const cell = row && row.querySelector ? row.querySelector('.url-cool-cell') : null;
    if (!cell || !cell.classList) return false;
    cell.classList.add('url-cool-cleared');
    setTimeout(() => cell.classList.remove('url-cool-cleared'), this.FLASH_MS);
    return true;
  },

  _rowOf(urlId) {
    const tbody = document.getElementById('urlTableBody');
    if (!tbody || !tbody.querySelectorAll) return null;
    return [...tbody.querySelectorAll('tr')].find(tr => String(tr.dataset.urlId) === String(urlId)) || null;
  },

  /** The row's ♻️ button: clear only this tab's active cooldown. */
  coolAction(btn) {
    const tabId = btn && btn.dataset ? btn.dataset.tabId : null;
    if (!tabId) { LogConsole.log('⚠ Tab not in pool — Connect it, then add to pool first', 'warn'); return; }
    this.clearTime(btn.dataset.urlId, btn.closest ? btn.closest('tr') : null);
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.UrlListReset = UrlListReset;

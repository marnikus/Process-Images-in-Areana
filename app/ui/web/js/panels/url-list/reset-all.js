/* url-list/reset-all.js — URL toolbar cooldown batch action.
   Shares the pool snapshot with UrlList, publishes resettable/busy state, and
   reports one concise result for the one canonical bridge operation. */
'use strict';
window.UrlListResetAll = {
  facade: null,
  resetButton: null,
  resetBusy: false,
  _toolbarBound: false,

  _bridge() { return window.App && window.App.bridge; },
  _parse(raw) { try { return typeof raw === 'string' ? JSON.parse(raw) : raw; } catch { return null; } },

  _listen(el, event, handler, key) {
    if (!el) return false;
    if (window.Boot) return window.Boot.bindOnce(el, event, handler, `url-reset:${key}`);
    el.addEventListener(event, handler);
    return true;
  },

  bindToolbar(facade) {
    this.facade = facade;
    if (this._toolbarBound) return true;
    this._toolbarBound = true;
    this.resetButton = document.getElementById('urlResetAllCooldownsBtn');
    this._listen(this.resetButton, 'click', () => this.resetAll(), 'all');
    setInterval(() => this.updateResetAllState((this.facade && this.facade.poolPages) || []), 1000);
    this.updateResetAllState(facade.poolPages || []);
    return true;
  },

  onPoolUpdate(payload) {
    const data = this._parse(payload), pages = data && Array.isArray(data.pages) ? data.pages : [];
    if (this.facade) {
      this.facade.poolPages = pages;
      if (this.facade._store) this.facade._store.poolPages = pages;
      const tbody = document.getElementById('urlTableBody');
      if (tbody && window.App?.state?.urls && this.facade._refreshFromSnap)
        this.facade._refreshFromSnap([...tbody.querySelectorAll('tr')], pages);
    }
    this.updateResetAllState(pages, Date.now());
  },

  updateResetAllState(pages, updatedAt) {
    if (!this.resetButton) return false;
    const snapAt = Number(updatedAt) || (window.PagePoolPanel && Number(window.PagePoolPanel.snapAt));
    const elapsed = snapAt > 0 ? Math.floor(Math.max(0, Date.now() - snapAt) / 1000) : 0;
    const canReset = (pages || []).some(page => {
      const timer = Number(page.cooldown_remaining) - elapsed > 0;
      const debt = Number(page.pending_penalty) > 0;
      const liveJob = !!page.current_image && ['busy', 'waiting_generation', 'waiting_captcha'].includes(page.status);
      return timer || (debt && !liveJob);
    });
    const disabled = this.resetBusy || !canReset;
    this.resetButton.disabled = disabled;
    this.resetButton.setAttribute('aria-disabled', String(disabled));
    return canReset;
  },

  resetAll() {
    const bridge = this._bridge();
    if (this.resetBusy || !this.resetButton || this.resetButton.disabled) return false;
    if (!bridge || typeof bridge.reset_all_cooldowns !== 'function') {
      LogConsole.log('Reset all cooldowns failed: bridge unavailable', 'error');
      return false;
    }
    this.resetBusy = true;
    this.resetButton.disabled = true;
    this.resetButton.setAttribute('aria-disabled', 'true');
    this.resetButton.setAttribute('aria-busy', 'true');
    try { bridge.reset_all_cooldowns(reply => this._onResetReply(reply)); }
    catch (error) { this._onResetReply({ ok: false, error: String(error) }); }
    return true;
  },

  _onResetReply(raw) {
    this.resetBusy = false;
    if (this.resetButton) this.resetButton.setAttribute('aria-busy', 'false');
    const reply = this._parse(raw);
    this.updateResetAllState((this.facade && this.facade.poolPages) || []);
    if (!reply || !reply.ok) {
      LogConsole.log(`Reset all cooldowns failed: ${(reply && reply.error) || 'invalid reply'}`, 'error');
      return;
    }
    this._reportReset(reply);
  },

  _reportReset(reply) {
    const result = this._resetOutcome(reply);
    if (result.problem) return this._reportResetFailure(result);
    this._reportResetSuccess(result);
  },

  _resetOutcome(reply) {
    const count = Math.max(0, Number(reply.reset) || 0);
    const failed = Array.isArray(reply.failed_tab_ids) ? reply.failed_tab_ids : [];
    const deferred = Array.isArray(reply.deferred_tab_ids) ? reply.deferred_tab_ids : [];
    const persisted = reply.persisted !== false, problem = failed.length > 0 || !persisted;
    const affected = persisted ? failed : [...new Set([...failed, ...(reply.reset_tab_ids || [])])];
    const names = problem ? this._workerNames(affected) : [];
    const tail = deferred.length ? `; ${deferred.length} live job(s) keep pending cooldown` : '';
    return { count, failed, deferred, persisted, problem, names, tail };
  },

  _reportResetFailure(result) {
    const problem = result.persisted ? 'could not reset' : 'persistence failed for';
    LogConsole.log(`Reset all cooldowns: ${result.count} reset; ${problem} ${result.names.join(', ') || 'affected workers'}${result.tail}`, 'warn');
  },

  _reportResetSuccess(result) {
    const plural = result.count === 1 ? '' : 's';
    const level = result.deferred.length ? 'warn' : 'success';
    LogConsole.log(`Reset all cooldowns: ${result.count} cooldown${plural} reset${result.tail}`, level);
  },

  _workerNames(ids) {
    const pages = (this.facade && this.facade.poolPages) || [];
    return [...new Set(ids.map(String))].map(id => {
      const page = pages.find(row => String(row.tab_id) === id);
      const label = page && (page.tab_label || window.TabLabel.of(id, page));
      return label && label !== id ? `${label} (${id})` : id;
    });
  },
};

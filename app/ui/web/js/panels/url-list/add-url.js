/* add-url.js — restores "add a page by URL" (BUG 03.1)
   RULE18: file 150-300, func <= 30, CC <= 10

   Root causes found in url-list/actions.js + url-list.js:
   1. `if (b && b.add_url) b.add_url(...)` — when the slot was not exposed by
      QWebChannel the click did literally nothing: no call, no error, no log.
   2. `UrlList.init()` early-returned when #urlTableBody was not mounted yet,
      leaving the Add button and the Enter key unbound for the whole session.
   3. `_onAdd` swallowed every parse error with `catch {}`, so a rejected URL
      ("already exists", "must start with http") looked like a dead button.

   This module binds through BridgeCall (never silent), validates client-side
   before the round trip, and re-renders from the returned state.
*/
'use strict';

window.UrlAdd = {
  requires: ['urlInput', 'urlAddBtn'],

  init() {
    const btn = document.getElementById('urlAddBtn');
    const input = document.getElementById('urlInput');
    btn.addEventListener('click', () => this.add());
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.add(); } });
    input.addEventListener('input', () => this.setError(''));
  },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
  },

  setError(msg) {
    const input = document.getElementById('urlInput');
    if (input) input.style.borderColor = msg ? 'var(--error, #bf616a)' : 'var(--border)';
    let hint = document.getElementById('urlAddError');
    if (!hint && msg && input) {
      hint = document.createElement('div');
      hint.id = 'urlAddError';
      hint.style.cssText = 'font-size:11px; color:var(--error, #bf616a); margin-top:4px;';
      input.parentNode.appendChild(hint);
    }
    if (hint) hint.textContent = msg || '';
  },

  /* Client-side gate mirrors app/ui/panels/url_queue._valid_new_url. */
  validate(raw) {
    const val = (raw || '').trim();
    if (!val) return { ok: false, error: 'Enter a page URL first' };
    if (!/^https?:\/\//i.test(val)) return { ok: false, error: 'URL must start with http:// or https://' };
    try { new URL(val); } catch (e) { return { ok: false, error: 'That is not a valid URL' }; }
    if (this._exists(val)) return { ok: false, error: 'This URL is already in the list' };
    return { ok: true, url: val };
  },

  _exists(url) {
    const rows = (window.App && App.state && App.state.urls) || [];
    return rows.some((u) => (u.url || '').trim() === url);
  },

  add() {
    const input = document.getElementById('urlInput');
    const check = this.validate(input ? input.value : '');
    if (!check.ok) { this.setError(check.error); this._log(`⚠ ${check.error}`, 'warn'); return; }
    this.setError('');
    this._disable(true);
    BridgeCall.invoke('add_url', [check.url], (r) => this._onAdded(check.url, r));
  },

  _disable(state) {
    const btn = document.getElementById('urlAddBtn');
    if (!btn) return;
    btn.disabled = !!state;
    btn.textContent = state ? 'Adding…' : 'Add';
  },

  _onAdded(url, r) {
    this._disable(false);
    if (r.queued) { this._log('Bridge not ready yet — retrying add', 'warn'); return; }
    if (r.ok === false) {
      this.setError(r.error || 'Add failed');
      this._log(`❌ Add URL failed: ${r.error || 'unknown error'}`, 'error');
      return;
    }
    const input = document.getElementById('urlInput');
    if (input) input.value = '';
    this._log(`✅ URL added: ${url}`, 'success');
    this.refreshList();
  },

  /* Pull fresh state instead of trusting a signal that may not arrive. */
  refreshList() {
    BridgeCall.invoke('get_arena_state', [], (r) => {
      const state = r.urls ? r : (r.value ? this._safe(r.value) : null);
      if (!state || !state.urls) return;
      if (window.App) App.state = state;
      if (window.UrlList && UrlList.render) UrlList.render(state.urls);
      const count = document.getElementById('urlCount');
      if (count) count.textContent = `${state.urls.length} URLs`;
    });
  },

  _safe(text) { try { return JSON.parse(text); } catch (e) { return null; } },
};

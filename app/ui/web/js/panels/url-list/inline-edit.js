/* url-list/inline-edit.js — shared inline editor for COOLDOWN and JOBS. */
'use strict';
window.UrlListInlineEdit = {
  _active: null,
  _bridge() { return window.App && window.App.bridge; },
  _fmt(s) { return window.PagePoolPanel ? window.PagePoolPanel.fmt(s) : `${s}s`; },
  _esc(s) { return window.UrlListStore ? window.UrlListStore.esc(s) : String(s || ''); },
  _reply(res, error = 'bad reply') { try { return JSON.parse(res); } catch { return { ok: false, error }; } },
  saveCooldown(payload, done) {
    const b = this._bridge();
    if (!payload.tabId || !b?.set_page_cooldown) return done({ ok: false, error: 'row tab not in pool' });
    b.set_page_cooldown(payload.tabId, payload.seconds, res => done(this._reply(res)));
  },
  saveJobs(payload, done) {
    const b = this._bridge();
    if (!payload.urlId || !b?.set_url_job_count) return done({ ok: false, error: 'row not found' });
    b.set_url_job_count(JSON.stringify({ url_id: payload.urlId, count: payload.count }), res => done(this._reply(res)));
  },
  buttonHtml(spec) {
    const width = Math.max(Number(spec.width) || 0, String(spec.text || '').length || 1);
    const data = this._attrs({ 'inline-field': spec.field, 'inline-value': spec.value, 'inline-text': spec.text, 'inline-width': width, 'inline-input-label': spec.inputLabel, 'url-id': spec.urlId, 'tab-id': spec.tabId || '' });
    return `<span class="url-inline-shell" style="--url-inline-width:${width}ch;">` + `<button type="button" class="url-inline-btn" ${data} aria-label="${this._esc(spec.buttonLabel || spec.inputLabel)}" title="${this._esc(spec.buttonTitle || spec.inputLabel)}">${this._esc(spec.text)}</button></span>`;
  },
  _attrs(obj) { return Object.entries(obj).map(([k, v]) => `data-${k}="${this._esc(v)}"`).join(' '); },
  isEditing(field, urlId) {
    const s = this._active;
    return !!s && s.field === field && String(s.urlId) === String(urlId);
  },
  onButtonKey(e, btn) {
    if (!btn || (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar')) return false;
    e.preventDefault();
    return this.start(btn);
  },
  cancel() {
    if (!this._active) return false;
    this._finish(this._active, null, true);
    return true;
  },
  start(btn) {
    const state = this._state(btn);
    if (!state) return false;
    if (this._active && this._active.input?.blur) this._active.input.blur();
    this._active = state;
    this._mountInput(state);
    return true;
  },
  _data(btn, key) { return btn?.dataset?.[key] || ''; },
  _buttonLabel(btn, field) { return btn.getAttribute?.('aria-label') || btn.title || `Edit ${field}`; },
  _state(btn) {
    const shell = btn?.parentElement, cfg = this._cfg(this._data(btn, 'inlineField'));
    if (!btn || !shell || !cfg) return null;
    const text = this._data(btn, 'inlineText') || btn.textContent || '';
    return {
      cfg, shell, field: cfg.field, urlId: this._data(btn, 'urlId'), tabId: this._data(btn, 'tabId'),
      originalText: text, originalValue: this._data(btn, 'inlineValue') || btn.textContent || '',
      width: Number(this._data(btn, 'inlineWidth')) || 1,
      inputLabel: this._data(btn, 'inlineInputLabel') || `Edit ${cfg.field}`,
      buttonLabel: this._buttonLabel(btn, cfg.field), done: false,
    };
  },
  _cfg(field) {
    return ({
      cooldown: { field: 'cooldown', save: (p, cb) => this.saveCooldown(p, cb), parse: raw => this._parseCooldown(raw) },
      jobs: { field: 'jobs', save: (p, cb) => this.saveJobs(p, cb), parse: raw => this._parseJobs(raw) },
    })[field] || null;
  },
  _mountInput(state) {
    const input = document.createElement('input');
    input.className = 'url-inline-input';
    input.type = 'text';
    input.value = state.originalValue;
    if (input.setAttribute) input.setAttribute('aria-label', state.inputLabel); else input.ariaLabel = state.inputLabel;
    input.style.width = `calc(${state.width}ch + 0px)`;
    input.addEventListener('keydown', e => this._onInputKey(e, state));
    input.addEventListener('blur', () => this._finish(state));
    state.shell.replaceChildren(input);
    state.input = input;
    input.focus?.();
    input.select?.();
  },
  _onInputKey(e, state) {
    if (e.key === 'Escape') { e.preventDefault(); this._finish(state, null, true); return; }
    if (e.key === 'Enter') { e.preventDefault(); this._finish(state); }
  },
  _finish(state, parsed = undefined, cancelled = false) {
    if (!state || state.done) return false;
    state.done = true;
    this._active = null;
    const next = cancelled ? null : (parsed === undefined ? state.cfg.parse(state.input?.value || '') : parsed);
    if (!next || next.raw === state.originalValue) {
      this._renderButton(state, state.originalText, state.originalValue);
      return !cancelled && !!next;
    }
    this._renderButton(state, next.text, next.raw);
    state.cfg.save({ urlId: state.urlId, tabId: state.tabId, ...next }, reply => this._afterSave(state, next, reply));
    return true;
  },
  _afterSave(state, next, reply) {
    if (reply?.ok) return;
    this._renderButton(state, state.originalText, state.originalValue);
    if (reply?.error && typeof LogConsole !== 'undefined') LogConsole.log(reply.error, 'error');
  },
  _renderButton(state, text, raw) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'url-inline-btn';
    btn.textContent = text;
    btn.dataset.inlineField = state.field;
    btn.dataset.inlineValue = raw;
    btn.dataset.inlineText = text;
    btn.dataset.inlineWidth = String(state.width);
    btn.dataset.inlineInputLabel = state.inputLabel;
    btn.dataset.urlId = state.urlId;
    btn.dataset.tabId = state.tabId;
    if (btn.setAttribute) btn.setAttribute('aria-label', state.buttonLabel); else btn.ariaLabel = state.buttonLabel;
    btn.title = state.buttonLabel;
    state.shell.replaceChildren(btn);
  },
  _parts(raw, want) {
    const bits = String(raw || '').trim().split(':');
    if (bits.length !== want || bits.some(x => !/^\d+$/.test(x))) return null;
    return bits.map(x => Number(x));
  },
  _seconds(parts) {
    if (parts.length === 2) return parts[1] > 59 ? null : parts[0] * 60 + parts[1];
    return parts[1] > 59 || parts[2] > 59 ? null : parts[0] * 3600 + parts[1] * 60 + parts[2];
  },
  _parseCooldown(raw) {
    const txt = String(raw || '').trim();
    const parts = this._parts(txt, 2) || this._parts(txt, 3);
    const secs = parts ? this._seconds(parts) : null;
    if (secs == null || secs < 0 || secs > 86400) return null;
    return { raw: this._fmt(secs), text: this._fmt(secs), seconds: secs };
  },
  _parseJobs(raw) {
    const txt = String(raw || '').trim();
    if (!/^\d+$/.test(txt)) return null;
    const num = Number(txt);
    if (!Number.isSafeInteger(num) || num < 0) return null;
    return { raw: String(num), text: String(num), count: num };
  },
};

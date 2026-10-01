/* url-list/inline-edit.js — shared accessible COOLDOWN/JOBS editor.
   Owns delegated keyboard/pointer editing and canonical bridge saves; displayed
   values remain derived from worker pool snapshots. */
'use strict';
window.UrlListInlineEdit = {
  active: null,
  facade: null,
  _bound: false,

  bind(facade) {
    this.facade = facade;
    if (this._bound) return true;
    this._bound = true;
    const table = document.getElementById('urlTableBody');
    this._listen(table, 'click', e => this.onValueClick(e), 'value-click');
    this._listen(table, 'keydown', e => this.onTableKey(e), 'value-key');
    this._listen(document, 'pointerdown', e => this.onOutside(e), 'outside-save');
    return true;
  },

  _listen(el, event, handler, key) {
    if (!el) return false;
    if (window.Boot) return window.Boot.bindOnce(el, event, handler, `url-inline:${key}`);
    el.addEventListener(event, handler);
    return true;
  },

  _bridge() { return window.App && window.App.bridge; },
  _log(message, level) { if (typeof LogConsole !== 'undefined') LogConsole.log(message, level); },
  _display(button, kind) {
    const clock = kind === 'cooldown' && button.querySelector('.url-cooldown-clock');
    return clock ? clock.textContent : (button.dataset.inlineValue || button.textContent);
  },

  fillJobsCell(tr, page) {
    const cell = tr.querySelector('.url-jobs-cell');
    if (!cell) return;
    if (!page) { cell.innerHTML = '<span style="color:var(--text-muted);" title="Tab not in pool">—</span>'; return; }
    const store = window.UrlListStore, tab = store.esc(page.tab_id || '');
    const label = store.esc(window.TabLabel.of(page.tab_id, page));
    const count = /^\d+$/.test(String(page.jobs_completed)) ? String(page.jobs_completed) : '0';
    const url = store.esc(tr.dataset.urlId || '');
    cell.innerHTML = `<button type="button" class="url-inline-value url-inline-jobs" data-inline-kind="jobs" data-tab-id="${tab}" data-inline-label="${label}" data-url-id="${url}" data-inline-value="${count}" aria-label="Jobs for ${label}" title="Click or press Enter to edit completed jobs">${count}</button>`;
  },

  cooldownHtml(page, urlId, format) {
    const left = page.cooldown_remaining || 0, total = page.cooldown_total || 0;
    const store = window.UrlListStore, tab = store.esc(page.tab_id || '');
    const label = store.esc(window.TabLabel.of(page.tab_id, page)), display = format(left);
    const title = store.esc(page.cooldown_reason || (left > 0 ? 'cooling' : 'no active timer'));
    const totalHtml = left > 0 && total > 0 ? `<span class="url-cooldown-total"> / ${format(total)}</span>` : '';
    return `<button type="button" class="url-inline-value url-inline-cooldown" data-inline-kind="cooldown" data-tab-id="${tab}" data-inline-label="${label}" data-url-id="${store.esc(urlId || '')}" data-inline-value="${display}" data-cool-seconds="${left}" aria-label="Cooldown for ${label}" title="Click or press Enter to edit cooldown"><span class="url-cooldown-clock" data-cool-tab="${tab}" data-cool-left="${left}" data-cool-at="${Date.now()}" title="${title}">${display}</span>${totalHtml}</button>`;
  },

  tick(root, format) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('.url-cool-cell [data-cool-left]').forEach(el => {
      const base = parseInt(el.getAttribute('data-cool-left') || '0', 10);
      const at = parseInt(el.getAttribute('data-cool-at') || '0', 10);
      const left = Math.max(0, base - Math.floor((Date.now() - at) / 1000));
      const display = format(left);
      el.textContent = display;
      const btn = el.closest('.url-inline-value');
      if (btn) btn.dataset.inlineValue = display;
      const total = el.parentElement && el.parentElement.querySelector('.url-cooldown-total');
      if (total && left <= 0) total.textContent = '';
    });
  },

  showClearedTime(row) {
    const cell = row && row.querySelector && row.querySelector('.url-cool-cell');
    const button = cell && cell.querySelector('.url-inline-cooldown');
    const clock = button && button.querySelector('.url-cooldown-clock');
    if (!button || !clock) return false;
    const at = String(Date.now()), zero = this._formatCooldown(0);
    clock.textContent = zero;
    clock.dataset.coolLeft = '0';
    clock.dataset.coolAt = at;
    if (clock.setAttribute) { clock.setAttribute('data-cool-left', '0'); clock.setAttribute('data-cool-at', at); }
    button.dataset.inlineValue = zero;
    button.dataset.coolSeconds = '0';
    const total = button.querySelector('.url-cooldown-total');
    if (total) total.textContent = '';
    return true;
  },

  onValueClick(event) {
    const button = event.target.closest('button.url-inline-value');
    if (button) this.open(button);
  },

  onTableKey(event) {
    const button = event.target.closest('button.url-inline-value');
    if (!button || !['Enter', ' ', 'Spacebar'].includes(event.key)) return;
    event.preventDefault();
    this.open(button);
  },

  onOutside(event) {
    if (this.active && !this._contains(this.active.input, event.target)) this.finish(true);
  },

  _contains(root, target) {
    for (let node = target; node; node = node.parentNode) if (node === root) return true;
    return false;
  },

  open(button) {
    const setup = this._openSetup(button);
    if (!setup) return false;
    this._mountInput(setup, this._createInput(button, setup));
    return true;
  },

  _openSetup(button) {
    const kind = button && button.dataset.inlineKind, parent = button && button.parentNode;
    if (!parent || this.active || !['cooldown', 'jobs'].includes(kind) || button.disabled) return null;
    return { button, parent, kind, tabId: button.dataset.tabId,
      value: this._display(button, kind), label: button.dataset.inlineLabel || button.dataset.tabId || '' };
  },

  _createInput(button, setup) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = `url-inline-input url-inline-input--${setup.kind}`;
    input.value = setup.value;
    input.setAttribute('aria-label', `${setup.kind === 'cooldown' ? 'Cooldown' : 'Jobs'} for ${setup.label}`);
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('inputmode', setup.kind === 'jobs' ? 'numeric' : 'text');
    input.setAttribute('spellcheck', 'false');
    const width = button.getBoundingClientRect ? button.getBoundingClientRect().width : 0;
    if (width > 0) input.style.width = `${Math.ceil(width)}px`;
    return input;
  },

  _mountInput(setup, input) {
    const { button, parent, kind, tabId, value } = setup;
    this.active = { button, input, parent, cell: button.closest('td'), kind,
      tabId, original: value, done: false };
    input.addEventListener('keydown', e => this.onInputKey(e));
    input.addEventListener('blur', () => this.finish(true));
    parent.replaceChild(input, button);
    input.focus();
    input.select();
  },

  onInputKey(event) {
    if (event.key !== 'Enter' && event.key !== 'Escape') return;
    event.preventDefault();
    if (event.stopPropagation) event.stopPropagation();
    this.finish(event.key === 'Enter');
  },

  normalizeCooldown(raw) {
    const text = String(raw ?? '').trim();
    if (!/^\d{1,2}:\d{2}(?::\d{2})?$/.test(text)) return null;
    const parts = text.split(':').map(Number);
    const seconds = parts.length === 2
      ? this._shortCooldownSeconds(parts) : this._longCooldownSeconds(parts);
    if (seconds === null) return null;
    return { seconds, display: this._formatCooldown(seconds) };
  },

  _shortCooldownSeconds(parts) {
    if (parts[0] > 59 || parts[1] > 59) return null;
    return parts[0] * 60 + parts[1];
  },

  _longCooldownSeconds(parts) {
    if (parts[0] > 24 || parts[1] > 59 || parts[2] > 59
        || (parts[0] === 24 && (parts[1] || parts[2]))) return null;
    return parts[0] * 3600 + parts[1] * 60 + parts[2];
  },

  _formatCooldown(seconds) {
    const s = Math.max(0, seconds), m = Math.floor(s / 60), sec = s % 60;
    if (m < 60) return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
  },

  normalizeJobs(raw) {
    const text = String(raw ?? '');
    if (!/^\d+$/.test(text)) return null;
    return { count: text.replace(/^0+(?=\d)/, '') || '0' };
  },

  _normalize(kind, raw) {
    return kind === 'cooldown' ? this.normalizeCooldown(raw) : this.normalizeJobs(raw);
  },

  finish(save) {
    const state = this.active;
    if (!state || state.done) return false;
    state.done = true;
    this.active = null;
    if (!save) { this._putBack(state); return false; }
    const value = this._normalize(state.kind, state.input.value);
    if (!value || this._same(state, value)) { this._putBack(state); return false; }
    this._setValue(state.button, state.kind, value);
    this._putBack(state);
    const bridge = this._bridge(), slot = state.kind === 'cooldown' ? 'set_page_cooldown' : 'set_page_job_count';
    if (!bridge || typeof bridge[slot] !== 'function') {
      this._restoreValue(state);
      this._log(`Could not edit ${state.kind}: bridge unavailable`, 'error');
      return false;
    }
    const payload = state.kind === 'cooldown' ? value.seconds : value.count;
    this._sendEdit(bridge, state, slot, payload);
    return true;
  },

  _sendEdit(bridge, state, slot, payload) {
    try { bridge[slot](state.tabId, payload, reply => this._onEditReply(state, reply)); }
    catch (error) { this._onEditReply(state, { ok: false, error: String(error) }); }
  },

  _same(state, value) {
    const old = this._normalize(state.kind, state.original);
    if (!old) return false;
    return state.kind === 'cooldown' ? old.display === value.display : old.count === value.count;
  },

  _putBack(state) {
    if (state.input.parentNode === state.parent) state.parent.replaceChild(state.button, state.input);
  },

  _setValue(button, kind, value) {
    if (kind === 'jobs') {
      button.textContent = value.count;
      button.dataset.inlineValue = value.count;
      return;
    }
    const clock = button.querySelector('.url-cooldown-clock');
    if (clock) {
      clock.textContent = value.display;
      clock.dataset.coolLeft = String(value.seconds);
      clock.dataset.coolAt = String(Date.now());
    } else button.textContent = value.display;
    button.dataset.inlineValue = value.display;
    button.dataset.coolSeconds = String(value.seconds);
    let total = button.querySelector('.url-cooldown-total');
    if (clock && value.seconds > 0 && !total) {
      total = document.createElement('span');
      total.className = 'url-cooldown-total';
      button.appendChild(total);
    }
    if (total) total.textContent = value.seconds > 0 ? ` / ${value.display}` : '';
  },

  _restoreValue(state) {
    const old = this._normalize(state.kind, state.original);
    if (old) this._setValue(state.button, state.kind, old);
  },

  _onEditReply(state, raw) {
    let reply;
    try { reply = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch { reply = null; }
    if (!reply || !reply.ok) {
      this._restoreValue(state);
      this._log(`Could not edit ${state.kind}: ${(reply && reply.error) || 'save failed'}`, 'error');
    }
  },

  isEditingCell(cell) { return !!this.active && this.active.cell === cell; },
};
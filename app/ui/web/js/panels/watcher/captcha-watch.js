/* captcha-watch.js — the Watcher is the only captcha UI (REFACTOR 02)
   RULE18: file 150-300, func <= 30, CC <= 10

   Replaces the captcha controls that used to live in #winCaptcha and in the
   run-controls / action-blocks windows. One switch, one truth:

     Watcher ON  -> pages are monitored, captchas are solved per page
     Watcher OFF -> nothing is monitored, nothing is solved, the app is only
                    responsible for image processing

   The panel never solves anything itself; it renders what
   app/services/captcha/watcher_gate.py reports.
*/
'use strict';

window.CaptchaWatch = {
  requires: ['winWatcher'],
  POLL_MS: 2000,
  _timer: null,
  _enabled: false,

  init() {
    this.mount();
    const toggle = document.getElementById('watcherCaptchaToggle');
    if (toggle) toggle.addEventListener('change', () => this.setSolving(toggle.checked));
    this.refresh();
    this._timer = setInterval(() => this.refresh(), this.POLL_MS);
  },

  stop() { if (this._timer) { clearInterval(this._timer); this._timer = null; } },

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
  },

  mount() {
    const host = document.getElementById('winWatcher');
    if (!host || document.getElementById('watcherCaptchaBox')) return;
    const box = document.createElement('div');
    box.id = 'watcherCaptchaBox';
    box.style.cssText = 'margin-top:8px; border-top:1px solid var(--border); padding-top:8px;';
    box.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; font-size:12px;">
        <label style="display:flex; align-items:center; gap:6px;">
          <input id="watcherCaptchaToggle" type="checkbox">
          <span>Solve captchas while watching</span>
        </label>
        <span id="watcherCaptchaState" style="font-size:11px; color:var(--text-muted);"></span>
      </div>
      <div id="watcherCaptchaPages" style="margin-top:6px; font-size:11px;"></div>`;
    host.appendChild(box);
  },

  setSolving(on) {
    BridgeCall.run('set_watcher_config', [JSON.stringify({ captcha_solving: !!on })], {
      failPrefix: 'Watcher captcha toggle failed',
      success: () => (on
        ? '🛡️ Watcher will solve captchas on watched pages'
        : '🛡️ Captcha solving off — pages are left to the user'),
      onOk: () => this.refresh(),
    });
  },

  refresh() {
    BridgeCall.invoke('get_captcha_status', [], (r) => {
      if (r.ok === false) { this.renderOff(r.error || 'status unavailable'); return; }
      this.render(r);
    });
  },

  renderOff(reason) {
    const state = document.getElementById('watcherCaptchaState');
    if (state) {
      state.textContent = reason === 'watcher_off'
        ? 'Watcher is OFF — no captcha solving'
        : `inactive (${reason})`;
      state.style.color = 'var(--text-muted)';
    }
    const pages = document.getElementById('watcherCaptchaPages');
    if (pages) pages.innerHTML = '';
  },

  render(status) {
    this._enabled = !!status.enabled;
    const toggle = document.getElementById('watcherCaptchaToggle');
    if (toggle) toggle.checked = this._enabled;
    if (!this._enabled) { this.renderOff(status.reason || 'watcher_off'); this.renderPages(status.pages); return; }
    const state = document.getElementById('watcherCaptchaState');
    if (state) {
      state.textContent = `solved ${status.solved || 0} · failed ${status.failed || 0} · skipped ${status.skipped || 0}`;
      state.style.color = 'var(--text-muted)';
    }
    this.renderPages(status.pages);
  },

  renderPages(pages) {
    const host = document.getElementById('watcherCaptchaPages');
    if (!host) return;
    const rows = Array.isArray(pages) ? pages : [];
    if (!rows.length) { host.innerHTML = ''; return; }
    host.innerHTML = rows.map((p) => this._pageRow(p)).join('');
  },

  _pageRow(p) {
    const tab = String(p.tab_id || '').slice(0, 8);
    const label = p.solved ? '✅ solved'
      : p.last_reason === 'watcher_off' ? '⏸ waiting for user'
        : `⏳ ${p.last_reason || 'detecting'} (try ${p.attempts || 0})`;
    return `<div style="display:flex; justify-content:space-between; gap:8px; padding:2px 0;">
      <span>tab ${tab}</span><span>${label}</span><span>${p.waiting_sec || 0}s</span></div>`;
  },
};

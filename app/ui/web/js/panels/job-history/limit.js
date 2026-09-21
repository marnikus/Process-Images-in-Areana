/* job-history/limit.js — the "show last N" display-count control.
   Two views of the one key `job_history_limit` (the history header input +
   the Settings mirror `#setHistoryLimit`) — this module owns both views; the
   header's Apply saves through the existing save_settings slot and the Settings
   mirror rides SettingsPanel's own payload, exactly like the interval control
   (D-1/I-61: one click = one save_settings, never a second listener on the
   Settings Save button). Bounds mirror app/services/job_history.py. */
'use strict';
const JobHistoryLimit = {
  MIN: 5, MAX: 500, DEFAULT: 50,
  INPUTS: ['historyLimit', 'setHistoryLimit'],
  _focused: false,

  init() {
    Boot.bindOnceById('historyLimitSaveBtn', 'click', () => this.save('historyLimit'), 'historyLimitSave');
    for (const id of this.INPUTS) {
      const input = document.getElementById(id);
      if (!input) continue;
      Boot.bindOnce(input, 'focus', () => { this._focused = true; }, `historyLimitFocus:${id}`);
      Boot.bindOnce(input, 'blur', () => { this._focused = false; }, `historyLimitBlur:${id}`);
    }
  },

  clamp(v) {
    const n = parseInt(v, 10);
    if (isNaN(n)) return this.DEFAULT;
    return Math.max(this.MIN, Math.min(n, this.MAX));
  },

  applyValue(n) {
    for (const id of this.INPUTS) {
      const input = document.getElementById(id);
      if (input && !this._focused) input.value = String(n);
    }
  },

  load(payload) {
    if (!payload || payload.limit === undefined) return;
    this.applyValue(this.clamp(payload.limit));
  },

  _announceSave(n, res) {
    try {
      const r = JSON.parse(res);
      if (typeof LogConsole !== 'undefined') LogConsole.log(r.ok ? `Job history shows last ${n} jobs` : 'History limit save failed: ' + r.error, r.ok ? 'success' : 'error');
    } catch {}
  },

  save(inputId) {
    const input = document.getElementById(inputId || 'historyLimit');
    const n = this.clamp(input ? input.value : this.DEFAULT);
    if (input) input.value = String(n);
    const call = Boot.needBridge('save_settings');
    if (!call) return;
    call(JSON.stringify({ job_history_limit: n }), (res) => this._announceSave(n, res));
  },
};
window.JobHistoryLimit = JobHistoryLimit;

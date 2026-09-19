/* watcher/render.js — UI rendering, ≤150 LOC, CC≤10 via helpers */
'use strict';
window.WatcherRender = {
  _store() { return window.WatcherStore; },

  _setText(id, txt) {
    const el=document.getElementById(id);
    if (el) el.textContent = txt;
  },

  _setBadge(text, bg, color) {
    const badge = document.getElementById('watcherStatusBadge');
    if (!badge) return;
    badge.textContent = text;
    badge.style.background = bg;
    badge.style.color = color;
  },

  _badgeForStatus(status) {
    const map = {
      waiting_captcha: { bg: 'rgba(180,20,20,0.9)', color: '#fff' },
      waiting_generation: { bg: 'rgba(20,80,180,0.9)', color: '#fff' },
      watching: { bg: 'var(--bg-success,#1a3a1a)', color: '#4ade80' },
    };
    return map[status] || { bg: 'var(--bg-input)', color: 'var(--text-muted)' };
  },

  _calcDuration(st) {
    if (st.waiting_duration !== undefined) return st.waiting_duration;
    if (!st.waiting_since) return 0;
    const d = Math.floor(Date.now()/1000 - st.waiting_since);
    if (isNaN(d) || d <0) return 0;
    return d;
  },

  _timeoutFor(st) {
    const cfg = st.config || this._store().config;
    if (st.waiting_kind === 'captcha') return cfg?.captcha_timeout_sec||300;
    return cfg?.generation_timeout_sec||600;
  },

  _waitingInfo(st) {
    if (!st.waiting_kind || !st.waiting_since) return '—';
    const durSec = this._calcDuration(st);
    const timeout = this._timeoutFor(st);
    return `${st.waiting_kind} for ${durSec||0}s (timeout ${timeout}s)`;
  },

  _genText(st) {
    if (!st.last_generation_details) return '—';
    try {
      const d = st.last_generation_details;
      if (d.details && Array.isArray(d.details)) {
        return `spinning=${d.spinning} count=${d.spinCount} labels=[${d.details.map(x=>x.label).join(',')}]`;
      }
      return JSON.stringify(d).slice(0,200);
    } catch (e) { return 'error'; }
  },

  _applyBadge(st) {
    const b = this._badgeForStatus(st.status || 'idle');
    this._setBadge(st.status || 'idle', b.bg, b.color);
  },

  _syncEnabledCheckbox(st) {
    const chk = document.getElementById('watcherEnabled');
    if (!chk) return;
    if (document.activeElement === chk) return;
    if (st.config && typeof st.config.enabled !== 'undefined') chk.checked = !!st.config.enabled;
  },

  render(data) {
    const st = data || this._store().state;
    if (!st) return;
    this._setText('watcherCurrentStatus', st.status || 'idle');
    this._setText('watcherLastCheck', st.last_check_human || st.last_check || 'never');
    this._setText('watcherChecksCount', st.checks_count || 0);
    this._setText('watcherGenWaits', st.generation_waits || 0);
    this._setText('watcherCaptchaWaits', st.captcha_waits || 0);
    this._setText('watcherLastCaptcha', st.last_captcha_detected ? 'true' : 'false');
    this._setText('watcherWaitingInfo', this._waitingInfo(st));
    this._setText('watcherLastGen', this._genText(st));
    this._applyBadge(st);
    this._syncEnabledCheckbox(st);
  },

  applyConfigToUI(cfg) {
    const setVal = (id, v) => { const el=document.getElementById(id); if(el) el.value=v; };
    const setChecked = (id, v) => { const el=document.getElementById(id); if(el) el.checked=!!v; };
    setChecked('watcherEnabled', cfg.enabled);
    setVal('watcherIntervalMs', cfg.check_interval_ms);
    setVal('watcherCaptchaTimeout', cfg.captcha_timeout_sec);
    setVal('watcherGenerationTimeout', cfg.generation_timeout_sec);
    setVal('watcherAutoPause', cfg.auto_pause_jobs ? 'true' : 'false');
  },
};

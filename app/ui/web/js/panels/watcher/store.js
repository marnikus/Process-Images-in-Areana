/* watcher/store.js — state + config, ≤100 LOC */
'use strict';
window.WatcherStore = {
  config: {
    enabled: false,
    check_interval_ms: 2000,
    captcha_timeout_sec: 300,
    generation_timeout_sec: 600,
    auto_pause_jobs: true,
  },
  state: {
    status: 'idle',
    last_check: 0,
    checks_count: 0,
    waiting_kind: null,
    waiting_since: null,
  },

  setConfig(cfg) {
    if (!cfg) return;
    this.config = {
      enabled: !!cfg.enabled,
      check_interval_ms: cfg.check_interval_ms || 2000,
      captcha_timeout_sec: cfg.captcha_timeout_sec || 300,
      generation_timeout_sec: cfg.generation_timeout_sec || 600,
      auto_pause_jobs: cfg.auto_pause_jobs !== false,
    };
  },

  setState(st) {
    if (!st) return;
    this.state = st;
    if (st.config) this.setConfig(st.config);
  },

  readInputs() {
    const getVal = (id) => document.getElementById(id)?.value;
    const getChecked = (id) => document.getElementById(id)?.checked;
    return {
      enabled: !!getChecked('watcherEnabled'),
      check_interval_ms: parseInt(getVal('watcherIntervalMs'))||2000,
      captcha_timeout_sec: parseInt(getVal('watcherCaptchaTimeout'))||300,
      generation_timeout_sec: parseInt(getVal('watcherGenerationTimeout'))||600,
      auto_pause_jobs: (getVal('watcherAutoPause')||'true')==='true',
    };
  },
};

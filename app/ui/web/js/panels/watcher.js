/* watcher.js — facade C15 ≤150 LOC, delegates to store/render/actions */
'use strict';

const WatcherPanel = {
  _store: null,
  _render: null,
  _actions: null,
  _pollTimer: null,

  get config() { return this._store ? this._store.config : {}; },
  set config(v) { if (this._store) this._store.config = v; },
  get state() { return this._store ? this._store.state : {}; },
  set state(v) { if (this._store) this._store.state = v; },

  init() {
    this._store = window.WatcherStore;
    this._render = window.WatcherRender;
    this._actions = window.WatcherActions;
    this._bindButtons();
    this._bindInputs();
    setTimeout(()=>this.loadConfig(), 1500);
    this._pollTimer = setInterval(()=>this.render(), 1000);
  },

  _bindButtons() {
    const map = {
      watcherEnabled: (e)=>{ this.config.enabled = e.target.checked; },
      watcherStartBtn: ()=>this.start(),
      watcherStopBtn: ()=>this.stop(),
      watcherCheckNowBtn: ()=>this.checkNow(),
      watcherClearOverlayBtn: ()=>this.clearOverlay(),
      watcherSaveBtn: ()=>this.save(),
    };
    Object.keys(map).forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const ev = id==='watcherEnabled' ? 'change' : 'click';
      el.addEventListener(ev, map[id]);
    });
  },

  _bindInputs() {
    const map = {
      watcherIntervalMs: (e)=>{ this.config.check_interval_ms = parseInt(e.target.value)||2000; },
      watcherCaptchaTimeout: (e)=>{ this.config.captcha_timeout_sec = parseInt(e.target.value)||300; },
      watcherGenerationTimeout: (e)=>{ this.config.generation_timeout_sec = parseInt(e.target.value)||600; },
      watcherAutoPause: (e)=>{ this.config.auto_pause_jobs = e.target.value==='true'; },
    };
    Object.keys(map).forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('change', map[id]);
    });
  },

  loadConfig() { return this._actions?.loadConfig(); },
  applyToUI() { return this._render?.applyConfigToUI(this.config); },
  save() { return this._actions?.save(); },
  start() { return this._actions?.start(); },
  stop() { return this._actions?.stop(); },
  checkNow() { return this._actions?.checkNow(); },
  clearOverlay() { return this._actions?.clearOverlay(); },
  refreshState() { return this._actions?.refreshState(); },
  onStatusUpdate(payload) { return this._actions?.onStatusUpdate(payload); },
  render(data) { return this._render?.render(data); },
};

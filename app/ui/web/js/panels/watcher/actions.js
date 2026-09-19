/* watcher/actions.js — bridge actions, ≤150 LOC, CC≤10 */
'use strict';
window.WatcherActions = {
  _store() { return window.WatcherStore; },
  _render() { return window.WatcherRender; },
  _bridge() { return window.App && window.App.bridge; },

  _onConfigLoaded(res, logCb) {
    try {
      const cfg = JSON.parse(res);
      if (cfg.error) { logCb('Watcher config load failed: '+cfg.error, 'warn'); return; }
      this._store().setConfig(cfg);
      this._render().applyConfigToUI(this._store().config);
      logCb(`Watcher config loaded: enabled=${this._store().config.enabled} interval=${this._store().config.check_interval_ms}ms`, 'info');
      if (this._store().config.enabled) {
        const badge = document.getElementById('watcherStatusBadge');
        if (badge) { badge.textContent='watching'; badge.style.background='var(--bg-success, #1a3a1a)'; badge.style.color='#4ade80'; }
      }
    } catch(e){ logCb('Watcher config parse failed: '+e, 'warn'); }
  },

  loadConfig() {
    const b = this._bridge();
    if (b?.get_watcher_config) {
      b.get_watcher_config((res)=> this._onConfigLoaded(res, (m,l)=>{ if(typeof LogConsole!=='undefined') LogConsole.log(m,l); }));
    }
    this.refreshState();
  },

  _onSave(res, payload, logCb) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        logCb(`Watcher saved: enabled=${payload.enabled} interval=${payload.check_interval_ms}ms`, 'success');
        this._render().applyConfigToUI(payload);
      } else {
        logCb('Watcher save failed: '+r.error, 'error');
      }
    } catch(e){ logCb('Watcher save parse failed: '+e, 'error'); }
  },

  save() {
    const payload = this._store().readInputs();
    this._store().setConfig(payload);
    const b = this._bridge();
    if (b?.set_watcher_config) {
      b.set_watcher_config(JSON.stringify(payload), (res)=> this._onSave(res, payload, (m,l)=>{ if(typeof LogConsole!=='undefined') LogConsole.log(m,l); }));
    }
  },

  _onStart(res, logCb) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        logCb('Watcher started — passive recheck every '+this._store().config.check_interval_ms+'ms', 'success');
        this._store().config.enabled = true;
        const chk = document.getElementById('watcherEnabled'); if (chk) chk.checked = true;
        const badge = document.getElementById('watcherStatusBadge'); if (badge) { badge.textContent='watching'; badge.style.background='var(--bg-success,#1a3a1a)'; badge.style.color='#4ade80'; }
      } else {
        logCb('Watcher start failed: '+r.error, 'error');
      }
    } catch(e){}
  },

  start() {
    const b = this._bridge();
    if (b?.start_watcher) b.start_watcher((res)=> this._onStart(res, (m,l)=>{ if(typeof LogConsole!=='undefined') LogConsole.log(m,l); }));
  },

  _onStop(res, logCb) {
    try {
      const r = JSON.parse(res);
      if (r.ok) {
        logCb('Watcher stopped', 'warn');
        this._store().config.enabled = false;
        const chk = document.getElementById('watcherEnabled'); if (chk) chk.checked = false;
        const badge = document.getElementById('watcherStatusBadge'); if (badge) { badge.textContent='idle'; badge.style.background='var(--bg-input)'; badge.style.color='var(--text-muted)'; }
      } else {
        logCb('Watcher stop failed: '+r.error, 'error');
      }
    } catch(e){}
  },

  stop() {
    const b = this._bridge();
    if (b?.stop_watcher) b.stop_watcher((res)=> this._onStop(res, (m,l)=>{ if(typeof LogConsole!=='undefined') LogConsole.log(m,l); }));
  },

  checkNow() {
    const b = this._bridge();
    if (b?.check_watcher_now) {
      b.check_watcher_now((res)=>{
        try {
          const r = JSON.parse(res);
          if(typeof LogConsole!=='undefined') LogConsole.log(r.ok ? 'Watcher check now queued' : 'Check now failed: '+r.error, r.ok?'info':'error');
        } catch(e){}
      });
    }
  },

  clearOverlay() {
    const b = this._bridge();
    if (b?.clear_watcher_overlay) {
      b.clear_watcher_overlay((res)=>{
        try {
          const r = JSON.parse(res);
          if(typeof LogConsole!=='undefined') LogConsole.log(r.ok ? 'Watcher overlay cleared' : 'Clear overlay failed: '+r.error, r.ok?'success':'error');
        } catch(e){}
      });
    }
  },

  refreshState() {
    const b = this._bridge();
    if (b?.get_watcher_state) {
      b.get_watcher_state((res)=>{
        try {
          const st = JSON.parse(res);
          if (st.error) return;
          this._store().setState(st);
          this._render().render(st);
        } catch(e){}
      });
    }
  },

  onStatusUpdate(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      this._store().setState(data);
      this._render().render(data);
    } catch(e){
      if(typeof LogConsole!=='undefined') LogConsole.log('Watcher status parse failed: '+e, 'warn');
    }
  },
};

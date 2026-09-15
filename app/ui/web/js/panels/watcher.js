/* watcher.js — Watcher win: passive recheck every x ms for generating icon or captcha
   - Checks div.animate-spin (generating) and Security Verification / reCAPTCHA (captcha)
   - Draws rectangle msg on left center page: "wait for finish generation" or "wait for user. Captcha"
   - Sleep circle run and wait it solve, with user-configurable timeout in win settings
   - All settings storable in session.json, window pos/size auto saved on closing
*/
'use strict';

const WatcherPanel = {
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
  _pollTimer: null,

  init() {
    // Buttons
    document.getElementById('watcherEnabled')?.addEventListener('change', (e)=>{ this.config.enabled = e.target.checked; });
    document.getElementById('watcherStartBtn')?.addEventListener('click', ()=>this.start());
    document.getElementById('watcherStopBtn')?.addEventListener('click', ()=>this.stop());
    document.getElementById('watcherCheckNowBtn')?.addEventListener('click', ()=>this.checkNow());
    document.getElementById('watcherClearOverlayBtn')?.addEventListener('click', ()=>this.clearOverlay());
    document.getElementById('watcherSaveBtn')?.addEventListener('click', ()=>this.save());

    // Inputs change
    document.getElementById('watcherIntervalMs')?.addEventListener('input', ()=>this.updateChromePreview?.());
    document.getElementById('watcherIntervalMs')?.addEventListener('change', (e)=>{ this.config.check_interval_ms = parseInt(e.target.value)||2000; });
    document.getElementById('watcherCaptchaTimeout')?.addEventListener('change', (e)=>{ this.config.captcha_timeout_sec = parseInt(e.target.value)||300; });
    document.getElementById('watcherGenerationTimeout')?.addEventListener('change', (e)=>{ this.config.generation_timeout_sec = parseInt(e.target.value)||600; });
    document.getElementById('watcherAutoPause')?.addEventListener('change', (e)=>{ this.config.auto_pause_jobs = e.target.value==='true'; });

    // Load config from backend after bridge ready
    setTimeout(()=>this.loadConfig(), 1500);

    // Listen to watcher_status signal from bridge (if available)
    if (window.App && App.bridge) {
      // Will be connected via bridge-ready.js
    }

    // Poll UI for state every 1s to update waiting duration
    this._pollTimer = setInterval(()=>this.render(), 1000);
  },

  loadConfig() {
    if (App.bridge && App.bridge.get_watcher_config) {
      App.bridge.get_watcher_config((res)=>{
        try {
          const cfg = JSON.parse(res);
          if (cfg.error) { LogConsole.log('Watcher config load failed: '+cfg.error, 'warn'); return; }
          this.config = {
            enabled: !!cfg.enabled,
            check_interval_ms: cfg.check_interval_ms || 2000,
            captcha_timeout_sec: cfg.captcha_timeout_sec || 300,
            generation_timeout_sec: cfg.generation_timeout_sec || 600,
            auto_pause_jobs: cfg.auto_pause_jobs !== false,
          };
          this.applyToUI();
          LogConsole.log(`Watcher config loaded: enabled=${this.config.enabled} interval=${this.config.check_interval_ms}ms captcha_to=${this.config.captcha_timeout_sec}s gen_to=${this.config.generation_timeout_sec}s`, 'info');
          // If enabled, ensure watcher started
          if (this.config.enabled) {
            // Status badge
            const badge = document.getElementById('watcherStatusBadge');
            if (badge) { badge.textContent = 'watching'; badge.style.background = 'var(--bg-success, #1a3a1a)'; badge.style.color = '#4ade80'; }
          }
        } catch(e){ LogConsole.log('Watcher config parse failed: '+e, 'warn'); }
      });
    }
    // Also get current state
    this.refreshState();
  },

  applyToUI() {
    const setVal = (id, v) => { const el=document.getElementById(id); if(el) el.value=v; };
    const setChecked = (id, v) => { const el=document.getElementById(id); if(el) el.checked=!!v; };
    setChecked('watcherEnabled', this.config.enabled);
    setVal('watcherIntervalMs', this.config.check_interval_ms);
    setVal('watcherCaptchaTimeout', this.config.captcha_timeout_sec);
    setVal('watcherGenerationTimeout', this.config.generation_timeout_sec);
    setVal('watcherAutoPause', this.config.auto_pause_jobs ? 'true' : 'false');
  },

  save() {
    // Read from UI
    const getVal = (id) => document.getElementById(id)?.value;
    const getChecked = (id) => document.getElementById(id)?.checked;
    const payload = {
      enabled: !!getChecked('watcherEnabled'),
      check_interval_ms: parseInt(getVal('watcherIntervalMs'))||2000,
      captcha_timeout_sec: parseInt(getVal('watcherCaptchaTimeout'))||300,
      generation_timeout_sec: parseInt(getVal('watcherGenerationTimeout'))||600,
      auto_pause_jobs: (getVal('watcherAutoPause')||'true')==='true',
    };
    this.config = payload;
    if (App.bridge && App.bridge.set_watcher_config) {
      App.bridge.set_watcher_config(JSON.stringify(payload), (res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log(`Watcher saved: enabled=${payload.enabled} interval=${payload.check_interval_ms}ms captcha=${payload.captcha_timeout_sec}s gen=${payload.generation_timeout_sec}s`, 'success');
            this.applyToUI();
          } else {
            LogConsole.log('Watcher save failed: '+r.error, 'error');
          }
        } catch(e){ LogConsole.log('Watcher save parse failed: '+e, 'error'); }
      });
    }
  },

  start() {
    if (App.bridge && App.bridge.start_watcher) {
      App.bridge.start_watcher((res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log('Watcher started — passive recheck every '+this.config.check_interval_ms+'ms', 'success');
            this.config.enabled = true;
            const chk = document.getElementById('watcherEnabled'); if (chk) chk.checked = true;
            const badge = document.getElementById('watcherStatusBadge'); if (badge) { badge.textContent='watching'; badge.style.background='var(--bg-success,#1a3a1a)'; badge.style.color='#4ade80'; }
          } else {
            LogConsole.log('Watcher start failed: '+r.error, 'error');
          }
        } catch(e){}
      });
    }
  },

  stop() {
    if (App.bridge && App.bridge.stop_watcher) {
      App.bridge.stop_watcher((res)=>{
        try {
          const r = JSON.parse(res);
          if (r.ok) {
            LogConsole.log('Watcher stopped', 'warn');
            this.config.enabled = false;
            const chk = document.getElementById('watcherEnabled'); if (chk) chk.checked = false;
            const badge = document.getElementById('watcherStatusBadge'); if (badge) { badge.textContent='idle'; badge.style.background='var(--bg-input)'; badge.style.color='var(--text-muted)'; }
          } else {
            LogConsole.log('Watcher stop failed: '+r.error, 'error');
          }
        } catch(e){}
      });
    }
  },

  checkNow() {
    if (App.bridge && App.bridge.check_watcher_now) {
      App.bridge.check_watcher_now((res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? 'Watcher check now queued' : 'Check now failed: '+r.error, r.ok?'info':'error');
        } catch(e){}
      });
    }
  },

  clearOverlay() {
    if (App.bridge && App.bridge.clear_watcher_overlay) {
      App.bridge.clear_watcher_overlay((res)=>{
        try {
          const r = JSON.parse(res);
          LogConsole.log(r.ok ? 'Watcher overlay cleared' : 'Clear overlay failed: '+r.error, r.ok?'success':'error');
        } catch(e){}
      });
    }
  },

  refreshState() {
    if (App.bridge && App.bridge.get_watcher_state) {
      App.bridge.get_watcher_state((res)=>{
        try {
          const st = JSON.parse(res);
          if (st.error) return;
          this.state = st;
          if (st.config) this.config = st.config;
          this.render(st);
        } catch(e){}
      });
    }
  },

  // Called from bridge-ready when watcher_status signal arrives
  onStatusUpdate(payload) {
    try {
      const data = typeof payload === 'string' ? JSON.parse(payload) : payload;
      this.state = data;
      if (data.config) {
        // Keep config in sync but don't overwrite UI if user editing? Just update
        this.config = data.config;
      }
      this.render(data);
    } catch(e){
      LogConsole.log('Watcher status parse failed: '+e, 'warn');
    }
  },

  render(data) {
    const st = data || this.state;
    if (!st) return;

    const setText = (id, txt) => { const el=document.getElementById(id); if(el) el.textContent = txt; };

    setText('watcherCurrentStatus', st.status || 'idle');
    setText('watcherLastCheck', st.last_check_human || st.last_check || 'never');
    setText('watcherChecksCount', st.checks_count || 0);
    setText('watcherGenWaits', st.generation_waits || 0);
    setText('watcherCaptchaWaits', st.captcha_waits || 0);
    setText('watcherLastCaptcha', st.last_captcha_detected ? 'true' : 'false');

    // Waiting info
    let waitingInfo = '—';
    if (st.waiting_kind && st.waiting_since) {
      const dur = st.waiting_duration || (st.waiting_since ? Math.floor(Date.now()/1000 - st.waiting_since) : 0);
      // Actually waiting_since is epoch seconds from backend, need to compute
      let durSec = st.waiting_duration;
      if (durSec === undefined && st.waiting_since) {
        durSec = Math.floor(Date.now()/1000 - st.waiting_since);
        if (isNaN(durSec) || durSec <0) durSec = 0;
      }
      waitingInfo = `${st.waiting_kind} for ${durSec||0}s`;
      if (st.waiting_kind === 'captcha') waitingInfo += ` (timeout ${st.config?.captcha_timeout_sec || this.config.captcha_timeout_sec}s)`;
      else waitingInfo += ` (timeout ${st.config?.generation_timeout_sec || this.config.generation_timeout_sec}s)`;
    }
    setText('watcherWaitingInfo', waitingInfo);

    // Last generation details
    let genTxt = '—';
    if (st.last_generation_details) {
      try {
        const d = st.last_generation_details;
        if (d.details && Array.isArray(d.details)) {
          genTxt = `spinning=${d.spinning} count=${d.spinCount} labels=[${d.details.map(x=>x.label).join(',')}]`;
        } else {
          genTxt = JSON.stringify(d).slice(0,200);
        }
      } catch(e){ genTxt = 'error'; }
    }
    setText('watcherLastGen', genTxt);

    // Badge color
    const badge = document.getElementById('watcherStatusBadge');
    if (badge) {
      badge.textContent = st.status || 'idle';
      if (st.status === 'waiting_captcha') {
        badge.style.background = 'rgba(180,20,20,0.9)'; badge.style.color = '#fff';
      } else if (st.status === 'waiting_generation') {
        badge.style.background = 'rgba(20,80,180,0.9)'; badge.style.color = '#fff';
      } else if (st.status === 'watching') {
        badge.style.background = 'var(--bg-success,#1a3a1a)'; badge.style.color = '#4ade80';
      } else {
        badge.style.background = 'var(--bg-input)'; badge.style.color = 'var(--text-muted)';
      }
    }

    // Also update enabled checkbox from state if not focused
    const enabledChk = document.getElementById('watcherEnabled');
    if (enabledChk && document.activeElement !== enabledChk) {
      if (st.config && typeof st.config.enabled !== 'undefined') {
        enabledChk.checked = !!st.config.enabled;
      }
    }
  }
};

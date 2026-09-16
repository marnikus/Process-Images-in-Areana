/* auto-connect.js — Auto-Connect & URL Parsing panel (spec 01-04)
   Backend does the work: it scans the CDP host:port from Settings, keeps every
   page whose URL contains the stored pattern, identifies pages by unique page id
   (the same URL twice is two pages), links them on start and re-scans on a timer
   plus on new-tab events. This panel only shows state and edits the settings:
   enabled, url pattern, interval, max pages, primary session — all storable.
*/
'use strict';

const AutoConnectPanel = {
  config: {
    enabled: true,
    url_pattern: 'arena.ai',
    interval_ms: 5000,
    max_pages: 0,
    connect_primary: true,
    host: '127.0.0.1',
    port: 9222,
  },
  status: null,
  _loaded: false,

  init() {
    document.getElementById('autoConnectSaveBtn')?.addEventListener('click', () => this.save());
    document.getElementById('autoConnectScanNowBtn')?.addEventListener('click', () => this.scanNow());
    document.getElementById('autoConnectScanBtn')?.addEventListener('click', () => this.scanNow());
    document.getElementById('autoConnectToggleBtn')?.addEventListener('click', () => this.toggle());
    document.getElementById('autoConnectPattern')?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.save();
    });
    setTimeout(() => this.load(), 1100);
  },

  bridge() {
    return (window.App && App.bridge) ? App.bridge : null;
  },

  load() {
    const b = this.bridge();
    if (!b || !b.get_autoconnect_config) return;
    b.get_autoconnect_config((res) => {
      try {
        const cfg = JSON.parse(res);
        if (cfg.error) { LogConsole.log('Auto-connect config load failed: ' + cfg.error, 'warn'); return; }
        this.applyConfig(cfg);
        this._loaded = true;
      } catch (e) { LogConsole.log('Auto-connect config parse failed: ' + e, 'warn'); }
    });
  },

  applyConfig(cfg) {
    if (!cfg) return;
    this.config = Object.assign(this.config, cfg);
    const setVal = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined && v !== null) el.value = v; };
    const setChk = (id, v) => { const el = document.getElementById(id); if (el && v !== undefined) el.checked = !!v; };
    setChk('autoConnectEnabled', cfg.enabled);
    setVal('autoConnectPattern', cfg.url_pattern || '');
    setVal('autoConnectInterval', cfg.interval_ms || 5000);
    setVal('autoConnectMaxPages', cfg.max_pages || 0);
    setChk('autoConnectPrimary', cfg.connect_primary);
    this.renderToolbar(cfg);
  },

  readForm() {
    const getVal = (id) => document.getElementById(id)?.value;
    const getChk = (id, fb) => { const el = document.getElementById(id); return el ? el.checked : fb; };
    let interval = parseInt(getVal('autoConnectInterval')) || 5000;
    interval = Math.max(1000, Math.min(600000, interval));
    let maxPages = parseInt(getVal('autoConnectMaxPages')) || 0;
    maxPages = Math.max(0, Math.min(100, maxPages));
    return {
      enabled: getChk('autoConnectEnabled', true),
      url_pattern: (getVal('autoConnectPattern') || '').trim(),
      interval_ms: interval,
      max_pages: maxPages,
      connect_primary: getChk('autoConnectPrimary', true),
    };
  },

  save() {
    const b = this.bridge();
    if (!b || !b.set_autoconnect_config) { LogConsole.log('Bridge not ready for auto-connect', 'warn'); return; }
    const payload = this.readForm();
    b.set_autoconnect_config(JSON.stringify(payload), (res) => {
      try {
        const r = JSON.parse(res);
        if (!r.ok) { LogConsole.log('Auto-connect save failed: ' + r.error, 'error'); return; }
        this.applyConfig(r.config || payload);
        if (typeof PagePoolPanel !== 'undefined') setTimeout(() => PagePoolPanel.refresh(), 600);
      } catch (e) { LogConsole.log('Auto-connect save parse failed: ' + e, 'warn'); }
    });
  },

  toggle() {
    const el = document.getElementById('autoConnectEnabled');
    const next = !(el ? el.checked : this.config.enabled);
    if (el) el.checked = next;
    LogConsole.log(next ? '🤖 Auto-connect turning ON — matching pages link themselves' : '🤖 Auto-connect turning OFF', next ? 'info' : 'warn');
    this.save();
  },

  scanNow() {
    const b = this.bridge();
    if (!b || !b.autoconnect_scan_now) { LogConsole.log('Bridge not ready for auto-connect scan', 'warn'); return; }
    this.setBadge('scanning…', 'rgba(20,80,180,0.9)', '#fff');
    b.autoconnect_scan_now((res) => {
      try {
        const r = JSON.parse(res);
        if (!r.ok) LogConsole.log('Scan now failed: ' + r.error, 'error');
      } catch (e) {}
    });
    if (typeof CDPPanel !== 'undefined' && CDPPanel.fetchTabs) setTimeout(() => CDPPanel.fetchTabs(), 1200);
    if (typeof PagePoolPanel !== 'undefined') setTimeout(() => PagePoolPanel.refresh(), 1500);
  },

  onStatus(payload) {
    try {
      const st = typeof payload === 'string' ? JSON.parse(payload) : payload;
      this.status = st;
      this.applyConfig(st);
      this.renderStatus(st);
      this.renderToolbar(st);
      if ((st.connected_now > 0 || (st.removed || []).length > 0) && typeof PagePoolPanel !== 'undefined') {
        PagePoolPanel.refresh();
      }
    } catch (e) { console.warn('auto-connect status failed', e); }
  },

  renderToolbar(st) {
    const cfg = st || this.config;
    const setText = (id, txt) => { const el = document.getElementById(id); if (el) el.textContent = txt; };
    setText('autoConnectPatternView', cfg.url_pattern || '(empty)');
    setText('autoConnectEndpointView', cfg.endpoint || `${cfg.host || '127.0.0.1'}:${cfg.port || 9222}`);
    setText('autoConnectIntervalView', Math.max(1, Math.round((cfg.interval_ms || 5000) / 1000)));
    const label = document.getElementById('autoConnectToggleLabel');
    if (label) label.textContent = cfg.enabled ? 'On' : 'Off';
    if (!cfg.enabled) {
      this.setBadge('off', 'var(--bg-input)', 'var(--text-muted)');
      setText('autoConnectCounts', 'automatic discovery disabled');
      return;
    }
    if (cfg.error) {
      this.setBadge('port unreachable', 'rgba(180,40,40,0.9)', '#fff');
    } else if (cfg.running) {
      this.setBadge(`watching · ${cfg.pool_total || 0} linked`, 'var(--bg-success,#1a3a1a)', '#4ade80');
    } else {
      this.setBadge('idle', 'var(--bg-input)', 'var(--text-muted)');
    }
    setText('autoConnectCounts',
      `scanned ${cfg.scanned || 0} · matched ${cfg.matched || 0} · linked ${cfg.pool_total || 0}` +
      `${cfg.duplicates ? ` · ${cfg.duplicates} dup id` : ''}` +
      `${(cfg.removed || []).length ? ` · ${cfg.removed.length} dropped` : ''}`);
  },

  renderStatus(st) {
    const el = document.getElementById('autoConnectStatus');
    if (!el) return;
    if (st.error) {
      el.textContent = `⚠ Scan failed on ${st.endpoint || ''}: ${st.error}`;
      el.style.color = 'var(--red,#ff6b6b)';
      return;
    }
    el.style.color = 'var(--text-muted)';
    const when = st.last_scan_at ? new Date(st.last_scan_at * 1000).toLocaleTimeString() : '—';
    const pats = (st.patterns || []).join(', ') || '(empty pattern)';
    el.textContent = `Last scan ${when} (${st.reason || 'scan'}) on ${st.endpoint || ''}: ` +
      `${st.scanned || 0} page(s), ${st.matched || 0} matched “${pats}”, ${st.connected_now || 0} newly linked, ` +
      `${st.pool_total || 0} in pool` +
      `${st.duplicates ? `, ${st.duplicates} duplicate page id(s) collapsed` : ''}` +
      `${(st.removed || []).length ? `, ${(st.removed || []).length} dropped` : ''}` +
      `${(st.failed || []).length ? `, ${(st.failed || []).length} failed` : ''}.`;
  },

  setBadge(text, bg, color) {
    const badge = document.getElementById('autoConnectBadge');
    if (!badge) return;
    badge.textContent = text;
    badge.style.background = bg;
    badge.style.color = color;
  },
};

/* firefox-auto.js — the "Firefox auto with Extension" window (18th window, I-63).
   Firefox stays a NORMAL visible browser: the signed Ui.Vision RPA add-on runs
   the macro (open URL → bringBrowserToForeground → pause → XClick → echo done)
   and this window drives the framework test — the config fields (the pattern
   is the control element), Save, Run, Stop and the live step stream.
   Self-connects to firefox_auto_updated (listeners.js stays frozen); all
   bridge traffic goes through Boot.needBridge. */
'use strict';

const FirefoxAutoPanel = {
  _connected: false,
  running: false,
  steps: [],

  /* element id → config key (one table: payload(), applyConfig() and the tests read it) */
  FIELDS: { faPattern: 'pattern', faUrlPattern: 'url_pattern', faMacro: 'macro',
            faTarget: 'target', faStorage: 'storage', faHome: 'home',
            faBinary: 'binary', faTimeout: 'timeout_sec', faPause: 'pause_ms' },

  NUMBERS: ['timeout_sec', 'pause_ms'],

  COLORS: { success: '#4caf50', warn: '#e6a23c', error: '#ff5c5c', info: 'var(--text-secondary)' },

  discoveredProfiles: [],

  init() {
    Boot.bindOnceById('faSaveBtn', 'click', () => this.save(), 'firefoxAutoSave');
    Boot.bindOnceById('faRunBtn', 'click', () => this.run(), 'firefoxAutoRun');
    Boot.bindOnceById('faStopBtn', 'click', () => this.stop(), 'firefoxAutoStop');
    Boot.bindOnceById('faShowProfilesBtn', 'click', () => this.toggleProfiles(), 'firefoxAutoShowProfiles');
    Boot.onBridgeReady(() => this._connect());
  },

  _connect() {
    const b = Boot._bridge();
    if (!b || this._connected) return;
    this._connected = true;
    if (b.firefox_auto_updated) b.firefox_auto_updated.connect((json) => this.onStatus(json));
    this.load();
  },

  _el(id) { return document.getElementById(id); },

  _val(id) { const el = this._el(id); return el ? el.value : ''; },

  _set(id, v) { const el = this._el(id); if (el && v !== undefined && v !== null) el.value = v; },

  _text(id, v) { const el = this._el(id); if (el) el.textContent = (v === undefined || v === null) ? '' : String(v); },

  _parse(json) {
    try { return typeof json === 'string' ? JSON.parse(json) : json; } catch { return null; }
  },

  /* ── config ─────────────────────────────────────────────────────────── */

  load() {
    const call = Boot.needBridge('get_firefox_auto_config');
    if (!call) return false;
    call((res) => this.applyPayload(this._parse(res)));
    return true;
  },

  applyPayload(p) {
    if (!p) return;
    if (p.profiles) this.discoveredProfiles = p.profiles;
    this.applyConfig(p.config || {});
    this.renderPaths(p.paths || {});
    this.setRunning(!!p.running);
  },

  applyConfig(cfg) {
    Object.keys(this.FIELDS).forEach((id) => this._set(id, cfg[this.FIELDS[id]]));
    const skipEl = this._el('faSkipMissingTab');
    if (skipEl) skipEl.checked = !!cfg.skip_missing_tab;
    this.renderProfilesList(cfg.selected_profiles || []);
  },

  configPayload() {
    const out = {};
    Object.keys(this.FIELDS).forEach((id) => {
      const key = this.FIELDS[id];
      out[key] = this.NUMBERS.includes(key) ? parseInt(this._val(id), 10) : String(this._val(id));
    });
    const skipEl = this._el('faSkipMissingTab');
    out.skip_missing_tab = skipEl ? !!skipEl.checked : false;
    out.selected_profiles = this.getSelectedProfiles();
    return out;
  },

  toggleProfiles() {
    const c = this._el('faProfilesContainer');
    if (!c) return;
    c.style.display = c.style.display === 'none' ? 'block' : 'none';
  },

  _isProfileChecked(p, selSet) {
    if (selSet.size === 0) return true;
    const name = (p.name || p.label || '').toLowerCase();
    const dir = (p.dir || '').toLowerCase();
    return selSet.has(name) || selSet.has(dir);
  },

  _createProfileRow(p, idx, checked) {
    const id = `fa_prof_${idx}`;
    const name = p.name || p.label || p.dir;
    const row = document.createElement('label');
    row.style.cssText = 'display:flex; align-items:center; gap:6px; cursor:pointer;';
    row.innerHTML = `<input type="checkbox" id="${id}" data-profile="${name}" ${checked ? 'checked' : ''}><span>${p.label || name}</span> <span style="color:var(--text-muted); font-size:9px;">(${p.dir})</span>`;
    return row;
  },

  renderProfilesList(selected) {
    const list = this._el('faProfilesList');
    if (!list) return;
    list.innerHTML = '';
    const profs = this.discoveredProfiles || [];
    if (profs.length === 0) {
      list.innerHTML = '<span style="color:var(--text-muted);">No Firefox profiles discovered</span>';
      return;
    }
    const selSet = new Set((selected || []).map((s) => String(s).toLowerCase()));
    profs.forEach((p, idx) => {
      list.appendChild(this._createProfileRow(p, idx, this._isProfileChecked(p, selSet)));
    });
  },

  getSelectedProfiles() {
    const list = this._el('faProfilesList');
    if (!list) return [];
    const inputs = list.querySelectorAll('input[type="checkbox"]');
    const selected = [];
    inputs.forEach((inp) => {
      if (inp.checked && inp.dataset.profile) selected.push(inp.dataset.profile);
    });
    return selected;
  },

  save() {
    const call = Boot.needBridge('save_firefox_auto_config');
    if (!call) return false;
    call(JSON.stringify(this.configPayload()), (res) => {
      const r = this._parse(res);
      if (!r) return;
      if (!r.ok) { this.setStatus(`⚠ save refused: ${r.error || 'unknown error'}`, 'warn'); return; }
      this.applyPayload(r);
      this.setStatus('✅ config saved', 'success');
    });
    return true;
  },

  /* ── run / stop ─────────────────────────────────────────────────────── */

  run() {
    const call = Boot.needBridge('run_firefox_auto_test');
    if (!call) return false;
    this.steps = [];
    this.renderSteps();
    call((res) => {
      const r = this._parse(res);
      if (r && !r.ok) this.setStatus(`⚠ ${r.error || 'run refused'}`, 'warn');
      else this.setRunning(true);
    });
    return true;
  },

  stop() {
    const call = Boot.needBridge('stop_firefox_auto_test');
    if (!call) return false;
    call((res) => {
      const r = this._parse(res);
      this.setStatus(r && !r.ok ? `⚠ ${r.error}` : '⏹ stop requested — the run ends on its next check',
        r && !r.ok ? 'warn' : 'info');
    });
    return true;
  },

  setRunning(running) {
    this.running = !!running;
    this._text('faState', this.running ? 'running…' : 'idle');
    const run = this._el('faRunBtn');
    if (run) run.disabled = this.running;
  },

  /* ── the status stream (one signal, JSON payloads — RULE 5) ─────────── */

  onStatus(json) {
    const p = this._parse(json);
    if (!p) return;
    if (p.kind === 'step') { this.addStep(p); return; }
    if (p.kind === 'saved') { this.applyConfig(p.config || {}); this.renderPaths(p.paths || {}); return; }
    if (p.kind === 'running') { this.setRunning(true); return; }
    if (p.kind === 'result') this.onResult(p);
  },

  addStep(p) {
    const mark = p.level === 'error' ? '✗' : (p.level === 'warn' ? '⚠' : '·');
    this.steps.push(`${mark} ${p.step}: ${p.message}`);
    if (this.steps.length > 60) this.steps = this.steps.slice(-60);
    this.renderSteps();
    this.setStatus(`${p.step} — ${p.message}`, p.level === 'success' ? 'success' : 'info');
  },

  onResult(p) {
    this.setRunning(false);
    const icon = p.result === 'ok' ? '✅'
      : (p.result === 'timeout' ? '⌛' : (p.result === 'stopped' ? '⏹' : '❌'));
    const level = p.result === 'ok' ? 'success' : (p.result === 'stopped' ? 'info' : 'warn');
    this.setStatus(`${icon} ${p.result}: ${p.message || ''}`, level);
    (p.lines || []).slice(-12).forEach((line) => this.steps.push(`  | ${line}`));
    this.renderSteps();
  },

  setStatus(text, level) {
    const el = this._el('faStatus');
    if (!el) return;
    el.textContent = text || '';
    el.style.color = this.COLORS[level] || this.COLORS.info;
  },

  renderSteps() {
    const el = this._el('faSteps');
    if (!el) return;
    el.textContent = this.steps.join('\n');
    el.scrollTop = el.scrollHeight;
  },

  renderPaths(paths) {
    const rows = [
      ['Ui.Vision home', paths.home], ['macro file', paths.macro_file],
      ['autorun page', paths.autorun_file], ['savelog dir', paths.log_dir],
    ].filter((pair) => pair[1]);
    this._text('faPaths', rows.map((pair) => `${pair[0]}: ${pair[1]}`).join('\n'));
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.FirefoxAutoPanel = FirefoxAutoPanel;

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
  profiles: [],        /* last fetched profile rows (from the bridge) */
  selectedProfiles: [], /* profile dirs the user checked ([] = every profile) */
  skipNoMatch: false,   /* skip a profile with no matching tab when true */

  /* element id → config key (one table: payload(), applyConfig() and the tests read it) */
  FIELDS: { faPattern: 'pattern', faUrlPattern: 'url_pattern', faMacro: 'macro',
            faTarget: 'target', faStorage: 'storage', faHome: 'home',
            faBinary: 'binary', faTimeout: 'timeout_sec', faPause: 'pause_ms',
            faWaitTimeout: 'wait_timeout_sec', faInterRunDelay: 'inter_run_delay_sec' },

  NUMBERS: ['timeout_sec', 'pause_ms', 'wait_timeout_sec', 'inter_run_delay_sec'],

  COLORS: { success: '#4caf50', warn: '#e6a23c', error: '#ff5c5c', info: 'var(--text-secondary)' },

  init() {
    Boot.bindOnceById('faSaveBtn', 'click', () => this.save(), 'firefoxAutoSave');
    Boot.bindOnceById('faRunBtn', 'click', () => this.run(), 'firefoxAutoRun');
    Boot.bindOnceById('faStopBtn', 'click', () => this.stop(), 'firefoxAutoStop');
    Boot.bindOnceById('faShowProfilesBtn', 'click', () => this.showProfiles(), 'firefoxAutoShowProfiles');
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
    this.applyConfig(p.config || {});
    this.renderPaths(p.paths || {});
    this.setRunning(!!p.running);
  },

  applyConfig(cfg) {
    Object.keys(this.FIELDS).forEach((id) => this._set(id, cfg[this.FIELDS[id]]));
    if (Array.isArray(cfg.selected_profiles)) this.selectedProfiles = cfg.selected_profiles.slice();
    if (cfg.skip_no_match !== undefined) {
      this.skipNoMatch = !!cfg.skip_no_match;
      const cb = this._el('faSkipNoMatch');
      if (cb) cb.checked = this.skipNoMatch;
    }
  },

  configPayload() {
    const out = {};
    Object.keys(this.FIELDS).forEach((id) => {
      const key = this.FIELDS[id];
      out[key] = this.NUMBERS.includes(key) ? parseInt(this._val(id), 10) : String(this._val(id));
    });
    out.selected_profiles = this._readSelectedProfiles();
    out.skip_no_match = !!(this._el('faSkipNoMatch') && this._el('faSkipNoMatch').checked);
    return out;
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

  /* ── profile selection (the "Show profiles" button) ─────────────────── */

  showProfiles() {
    const call = Boot.needBridge('show_firefox_profiles');
    if (!call) return false;
    call((res) => {
      const r = this._parse(res);
      if (!r || !r.ok) { this.setStatus(`⚠ profiles: ${(r && r.error) || 'unknown error'}`, 'warn'); return; }
      this.profiles = r.profiles || [];
      if (Array.isArray(r.selected)) this.selectedProfiles = r.selected.slice();
      if (r.skip_no_match !== undefined) {
        this.skipNoMatch = !!r.skip_no_match;
        const cb = this._el('faSkipNoMatch');
        if (cb) cb.checked = this.skipNoMatch;
      }
      this.renderProfiles();
    });
    return true;
  },

  renderProfiles() {
    const el = this._el('faProfileList');
    if (!el) return;
    if (!this.profiles.length) { el.innerHTML = '<em>No Firefox profile readable.</em>'; return; }
    const sel = new Set(this.selectedProfiles);
    const allChecked = sel.size === 0;  /* blank = every profile */
    const rows = this.profiles.map((p) => {
      const checked = allChecked || sel.has(p.id);
      const name = p.name || p.dir.split(/[\\/]/).pop();
      const tabs = (p.tabs || []).slice(0, 6).map((u) => u.replace(/^https?:\/\//, '').slice(0, 50)).join(', ');
      const extra = (p.tab_count || 0) > 6 ? `, +${p.tab_count - 6} more` : '';
      return `<label style="display:flex; align-items:flex-start; gap:4px; padding:2px 0; cursor:pointer;">` +
        `<input type="checkbox" class="fa-profile-cb" data-profile-id="${this._escAttr(p.id)}" ${checked ? 'checked' : ''}>` +
        `<span><b>${this._esc(name)}</b> <span style="color:var(--text-muted);">(${p.tab_count || 0} tab(s))</span>` +
        (tabs ? `<br><span style="font-size:10px; color:var(--text-muted);">${this._esc(tabs)}${this._esc(extra)}</span>` : '') +
        `</span></label>`;
    });
    el.innerHTML = rows.join('');
    el.querySelectorAll('.fa-profile-cb').forEach((cb) => {
      cb.addEventListener('change', () => this._onProfileCheckChanged());
    });
  },

  _onProfileCheckChanged() {
    this.selectedProfiles = this._readSelectedProfiles();
  },

  _readSelectedProfiles() {
    const el = this._el('faProfileList');
    if (!el) return [];
    const boxes = el.querySelectorAll('.fa-profile-cb');
    if (!boxes.length) return [];
    const checked = [];
    boxes.forEach((cb) => { if (cb.checked) checked.push(cb.getAttribute('data-profile-id') || ''); });
    /* When every box is checked, treat as "all" — same as blank. */
    return checked.length === boxes.length ? [] : checked.filter(Boolean);
  },

  _esc(text) { return String(text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },

  _escAttr(text) { return String(text || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.FirefoxAutoPanel = FirefoxAutoPanel;

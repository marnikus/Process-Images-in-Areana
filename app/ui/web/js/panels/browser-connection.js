/* browser-connection.js — the Settings "Browser Debug Connection" block (2026-09-22)
   One registry, one browser: Chrome and its CDP endpoint. (Firefox/Edge rows and
   the prefs/stealth/Prepare-Profile machinery went with the debugger approach —
   a normal Firefox is automated through the Ui.Vision extension in its own
   window, "Firefox auto with Extension", never from this block.)

   The browser table (binaries, dir flag, port offset, capabilities, notes) lives
   in `app/browser/browsers.py` and reaches the page through `get_cdp_config` —
   adding a browser back is one Python row, no JS change. This module renders
   whatever the payload says and keeps only a one-entry id/label fallback for
   the first paint.

   Ports: the shared setting is the BASE port and each registry row derives
   base + its offset (Chrome +0); a hand-edited row port overrides. The panel
   always shows the resolved number.

   RULE18: file ≤300, func ≤30, CC≤10, ≤4 params.
*/
'use strict';

const BrowserConnection = {
  FALLBACK: [
    { id: 'chrome', label: 'Chrome' },
  ],
  browsers: null,      // payload rows in registry order (null = fallback)
  active: '',

  init() {
    this.bind();
    this.apply(null);  // first paint: the fallback ids, everything else from the bridge
  },

  _el(id) { return document.getElementById(id); },

  _val(id) {
    const el = this._el(id);
    return el ? el.value : '';
  },

  _set(id, v) {
    const el = this._el(id);
    if (el && v !== undefined && v !== null) el.value = v;
  },

  _text(id, v) {
    const el = this._el(id);
    if (el) el.textContent = (v === undefined || v === null) ? '' : String(v);
  },

  bind() {
    const sel = this._el('browserSelect');
    if (sel) sel.addEventListener('change', () => this.onSelectChange());
  },

  rows() { return (this.browsers && this.browsers.length) ? this.browsers : this.FALLBACK; },

  browser(id) {
    const want = id || this.active || ((this.rows()[0] || {}).id);
    return this.rows().find((b) => b.id === want) || null;
  },

  basePort() {
    const base = parseInt(this._val('cdpPort'), 10);
    return Number.isFinite(base) ? base : 9222;
  },

  resolvedPort(b) {
    if (!b) return '';
    return this.basePort() + (b.port_offset || 0);
  },

  /* ── the payload is the source of truth ─────────────────────────────── */

  apply(payload) {
    if (payload && Array.isArray(payload.browsers) && payload.browsers.length) this.browsers = payload.browsers;
    if (payload) {
      this._set('cdpHost', payload.host);
      this._set('cdpPort', payload.port);
      this._set('cdpUrlPattern', payload.url_pattern);
    }
    this.renderOptions(payload && payload.active_browser);
    this.showBrowser((payload && payload.active_browser) || '');
    this.renderScanLine(payload);
  },

  /* What one Refresh pass asks — built in Python (`browsers.scan_line`), shown as-is.
     The panel says which endpoints those are (and which browser is switched off). */
  renderScanLine(payload) {
    const el = this._el('cdpScanLine');
    if (!el) return;
    if (payload && payload.scan_line) { el.textContent = payload.scan_line; return; }
    const host = (payload && payload.host) || this._val('cdpHost') || '127.0.0.1';
    const parts = this.rows().map((b) => (b.enabled === false
      ? `${b.id} — off`
      : `${b.id} ${host}:${b.resolved_port} (${String(b.protocol || 'cdp').toUpperCase()})`));
    el.textContent = parts.length ? `Scanning: ${parts.join(' · ')}` : 'Scanning: —';
  },

  renderOptions(activeId) {
    const sel = this._el('browserSelect');
    if (!sel) return;
    const prev = sel.value || '';
    sel.innerHTML = '';
    this.rows().forEach((b) => sel.appendChild(this._option(b)));
    const want = activeId || prev || (this.rows()[0] || {}).id || '';
    if (want) sel.value = want;
  },

  _option(b) {
    const opt = document.createElement('option');
    opt.value = b.id;
    const where = b.resolved_port ? ` on ${b.resolved_port}` : '';
    opt.title = b.protocol
      ? `${b.label || b.id} — ${String(b.protocol).toUpperCase()}${where}`
      : (b.label || b.id);
    opt.textContent = b.label || b.id;
    return opt;
  },

  /* ── selection + per-browser block ──────────────────────────────────── */

  onSelectChange() {
    const sel = this._el('browserSelect');
    if (!sel || !sel.value) return;
    this.stash();
    this.showBrowser(sel.value);
    this.updateToolbar();
  },

  stash() {
    const b = this.browser();
    if (!b) return;
    b.user_data_dir = this._val('cdpUserDataDir');
    b.extra_args = this._val('cdpExtraArgs');
  },

  showBrowser(id) {
    const b = this.browser(id);
    if (!b) return;
    this.active = b.id;
    const sel = this._el('browserSelect');
    if (sel && sel.value !== b.id) sel.value = b.id;
    this._set('cdpUserDataDir', b.user_data_dir || '');
    this._set('cdpExtraArgs', b.extra_args || '');
    this._text('cdpResolvedPort', this.resolvedPort(b));
    this._text('cdpTestUrl', b.test_url || '');
    this.renderFacts(b);
    this._text('cdpLaunchCmd', this.commandText(b));
    this.updateToolbar();
  },

  renderFacts(b) {
    this._text('cdpCapabilities', this.capabilityText(b));
    this._text('cdpBrowserNotes', (b.dir_flag ? `${b.dir_flag} — ` : '') + (b.notes || ''));
    this._text('cdpDirLabel', this.dirLabel(b));
  },

  /* Which profile dir the launch command will carry — empty means the browser's own. */
  dirLabel(b) {
    const flag = b.dir_flag ? ` (${b.dir_flag})` : '';
    const configured = b.user_data_dir || this._val('cdpUserDataDir');
    if (configured) return `Profile dir for ${b.label || b.id}${flag}`;
    return `No dir configured for ${b.label || b.id}${flag}: the browser's own profile is used`;
  },

  /* ✅ what works, ⛔ what the protocol cannot do — named, never a silent timeout */
  capabilityText(b) {
    const ok = b.capabilities || [];
    const no = b.unavailable || [];
    const parts = [];
    if (ok.length) parts.push(`✅ ${ok.join(', ')}`);
    if (no.length) parts.push(`⛔ not in ${String(b.protocol || '').toUpperCase()}: ${no.join(', ')}`);
    return parts.join('  ·  ') || '—';
  },

  /* ── the launch command + test URL ──────────────────────────────────── */

  /* The bridge's own command wins (it knows the OS); the local composition keeps
     the preview honest while the fields are being edited. */
  commandText(b) {
    const fromBridge = b.commands && b.commands.windows;
    if (fromBridge) return fromBridge;
    return b.binary ? this.compose(b) : '— waiting for the bridge to build the command —';
  },

  /* Live edit: recompose from the fields that were just typed. */
  updatePreview() {
    const b = this.browser();
    if (!b) return;
    this._text('cdpLaunchCmd', b.binary ? this.compose(b) : this.commandText(b));
  },

  compose(b) {
    const dir = this._val('cdpUserDataDir');
    const parts = [b.binary, `--remote-debugging-port=${this.resolvedPort(b)}`];
    if (dir) parts.push(`${b.dir_flag || '--user-data-dir'}="${dir}"`);
    const extra = (this._val('cdpExtraArgs') || '').trim();
    if (extra) parts.push(extra);
    return parts.join(' ');
  },

  applyLaunch(payload) {
    if (!payload || !payload.windows) return;
    if (payload.browser && payload.browser !== this.active) return;
    this._text('cdpLaunchCmd', payload.windows);
  },

  toolbarConfig() {
    const b = this.browser() || {};
    return { host: this._val('cdpHost'), port: this.resolvedPort(b), browser: this.active,
      user_data_dir: this._val('cdpUserDataDir'), extra_args: this._val('cdpExtraArgs'),
      command: this._val('cdpUserDataDir') ? this.compose(b) : '' };
  },

  updateToolbar() {
    if (!this.browsers) return;   // no payload yet — the CDP panel paints itself at its own init
    if (typeof CDPPanel !== 'undefined' && CDPPanel.updateChromeToolbar) CDPPanel.updateChromeToolbar(this.toolbarConfig());
  },

  /* ── what Save sends to the bridge ──────────────────────────────────── */

  payload() {
    this.stash();
    return {
      browser: this.active,
      host: this._val('cdpHost') || '127.0.0.1',
      port: this.basePort(),
      url_pattern: (this._val('cdpUrlPattern') || '').trim(),
      user_data_dir: this._val('cdpUserDataDir'),
      extra_args: this._val('cdpExtraArgs'),
      browsers: this.browserMap(),
    };
  },

  browserMap() {
    const out = {};
    this.rows().forEach((b) => {
      out[b.id] = { enabled: true, port: this.resolvedPort(b),
        user_data_dir: b.user_data_dir || '', extra_args: b.extra_args || '' };
    });
    return out;
  },
};

// Global-name contract (see boot.js): publish the lexical const for window[name] lookups.
if (typeof window !== 'undefined') window.BrowserConnection = BrowserConnection;

/* uivision.js — the "Firefox auto with Extension" window (18th window).
   Ui.Vision RPA drives a normal Firefox tab with native OS clicks; this panel
   edits the config, shows the macro source, and starts the XClick test. The
   verdict is asynchronous (Python polls the Ui.Vision log), so it arrives on
   the uivision_result signal rather than as the slot's return value. */
'use strict';
const UiVisionPanel = {
  _connected: false,

  init() {
    Boot.bindOnceById('uivSaveBtn', 'click', () => this.save(), 'uivSave');
    Boot.bindOnceById('uivRunBtn', 'click', () => this.run(), 'uivRun');
    Boot.bindOnceById('uivMacroBtn', 'click', () => this.showMacro(), 'uivMacro');
    Boot.onBridgeReady(() => this._connect());
  },

  _connect() {
    const b = Boot._bridge();
    if (!b || this._connected) return;
    this._connected = true;
    if (b.uivision_result) b.uivision_result.connect((json) => this.onResult(json));
    this.refresh();
  },

  _parse(json) {
    try { return typeof json === 'string' ? JSON.parse(json) : json; } catch { return null; }
  },

  /* Pull the saved config and show which tab the pattern resolves to. */
  refresh() {
    const b = Boot._bridge();
    if (!b || !b.get_uivision_settings) return;
    b.get_uivision_settings((json) => {
      const p = this._parse(json);
      if (!p) return;
      window.UiVisionForm.load(p);
      window.UiVisionRender.match(p);
    });
  },

  save() {
    const b = Boot._bridge();
    const values = window.UiVisionForm.collect();
    if (!b || !b.save_uivision_settings) return;
    b.save_uivision_settings(JSON.stringify(values), (json) => {
      const p = this._parse(json);
      if (p) window.UiVisionRender.match(p);
    });
  },

  /* Start the macro. Success here only means "launched" — see onResult. */
  run() {
    const b = Boot._bridge();
    if (!b || !b.run_uivision_test) return;
    window.UiVisionRender.status('running', 'running…');
    b.run_uivision_test((json) => {
      const p = this._parse(json);
      if (p && !p.ok) {
        window.UiVisionRender.status('failed', 'failed');
        window.UiVisionRender.outcome(p);
      }
    });
  },

  /* The logged verdict, once Python has finished polling the log file. */
  onResult(json) {
    const p = this._parse(json);
    if (!p) return;
    window.UiVisionRender.status(p.ok ? 'ok' : 'failed', p.ok ? 'done' : (p.state || 'failed'));
    window.UiVisionRender.outcome(p);
  },

  showMacro() {
    const b = Boot._bridge();
    if (!b || !b.get_uivision_macro) return;
    b.get_uivision_macro((json) => {
      const p = this._parse(json);
      if (p && p.ok) window.UiVisionRender.macro(p.macro);
    });
  },
};
window.UiVisionPanel = UiVisionPanel;

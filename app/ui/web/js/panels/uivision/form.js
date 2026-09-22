/* uivision/form.js — the Ui.Vision window's fields: read, write, validate.
   One field id ↔ one config key, kept in FIELDS so the form and the Python
   SETTING_KEYS cannot drift apart silently. */
'use strict';
const UiVisionForm = {
  FIELDS: {
    uivHtmlPath: 'uivision_html_path',
    uivMacro: 'uivision_macro',
    uivLogPath: 'uivision_log_path',
    uivFirefoxPath: 'uivision_firefox_path',
    uivTabPattern: 'uivision_tab_pattern',
    uivTarget: 'uivision_target',
    uivTimeout: 'uivision_timeout_s',
  },

  _el(id) { return document.getElementById(id); },

  /* Fill the form from a settings payload (missing keys leave the field alone). */
  load(payload) {
    if (!payload) return;
    Object.entries(this.FIELDS).forEach(([id, key]) => {
      const el = this._el(id);
      if (el && payload[key] !== undefined && payload[key] !== null) el.value = payload[key];
    });
  },

  /* The form's current values, keyed the way Python stores them. */
  collect() {
    const out = {};
    Object.entries(this.FIELDS).forEach(([id, key]) => {
      const el = this._el(id);
      if (!el) return;
      out[key] = key === 'uivision_timeout_s' ? (parseFloat(el.value) || 60) : (el.value || '').trim();
    });
    return out;
  },

  /* What is still missing, in the operator's words ([] when ready). */
  gaps(values) {
    const missing = [];
    if (!values.uivision_html_path) missing.push('ui.vision.html path');
    if (!values.uivision_log_path) missing.push('log file path');
    if (!values.uivision_macro) missing.push('macro name');
    return missing;
  },
};
window.UiVisionForm = UiVisionForm;

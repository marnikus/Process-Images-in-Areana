/* panel-boot.js — fault-isolated panel start-up (BUG 03.5 root cause)
   RULE18: file 150-300, func <= 30, CC <= 10

   Before (arena-app.js):
       _PANEL_INITS.forEach(_initIfExists);
   One panel throwing (ArenaPresets.init() -> this._actions is undefined)
   aborted the whole loop, so every panel after it never bound a listener.
   That single line is why "action blocks disappeared" and "many buttons do
   nothing" arrived together.

   After: each panel boots inside its own try/catch, failures are reported,
   and panels whose DOM was not mounted yet are retried.
*/
'use strict';

window.PanelBoot = {
  RETRY_MS: 400,
  MAX_RETRIES: 5,
  results: {},

  _log(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'info');
    else console.log(msg);
  },

  /* A panel may declare `requires: ['elementId', ...]`. Missing ids mean
     "not mounted yet" -> retry, instead of binding nothing forever. */
  _missingDom(panel) {
    const need = panel && panel.requires;
    if (!Array.isArray(need)) return [];
    return need.filter((id) => !document.getElementById(id));
  },

  _record(name, status, detail) {
    this.results[name] = { status, detail: detail || '', at: Date.now() };
    return this.results[name];
  },

  _bootOne(name, attempt) {
    const panel = window[name];
    if (!panel) return this._record(name, 'absent', 'global not defined');
    if (typeof panel.init !== 'function') return this._record(name, 'absent', 'no init()');
    const missing = this._missingDom(panel);
    if (missing.length) {
      if (attempt < this.MAX_RETRIES) {
        setTimeout(() => this._bootOne(name, attempt + 1), this.RETRY_MS);
        return this._record(name, 'waiting', `dom: ${missing.join(', ')}`);
      }
      this._log(`⚠ ${name}: DOM ids never appeared (${missing.join(', ')})`, 'warn');
      return this._record(name, 'failed', `missing dom: ${missing.join(', ')}`);
    }
    try {
      panel.init();
      return this._record(name, 'ok');
    } catch (e) {
      this._log(`❌ ${name}.init() failed: ${e.message}`, 'error');
      console.error(`[PanelBoot] ${name}.init()`, e);
      return this._record(name, 'failed', e.message);
    }
  },

  /* Boot every panel. One failure can no longer stop the others. */
  bootAll(names) {
    (names || []).forEach((name) => this._bootOne(name, 0));
    return this.summary();
  },

  summary() {
    const rows = Object.entries(this.results);
    const failed = rows.filter(([, r]) => r.status === 'failed');
    const absent = rows.filter(([, r]) => r.status === 'absent');
    if (failed.length) {
      this._log(`❌ ${failed.length} panel(s) failed to start: ${failed.map(([n]) => n).join(', ')}`, 'error');
    }
    if (absent.length) {
      console.warn('[PanelBoot] not loaded:', absent.map(([n]) => n).join(', '));
    }
    if (!failed.length) this._log(`✅ ${rows.length - absent.length} panels started`, 'success');
    return { total: rows.length, failed: failed.length, absent: absent.length };
  },

  /* Re-run init for one panel (used after a window is re-opened). */
  reboot(name) { return this._bootOne(name, 0); },

  /* Diagnostics for the Settings window. */
  report() {
    return Object.entries(this.results)
      .map(([name, r]) => ({ panel: name, status: r.status, detail: r.detail }));
  },
};

/* Drop-in replacement for arena-app.js initApp():

     function initApp() {
       setupHeader();
       PanelBoot.bootAll(_PANEL_INITS);
       document.getElementById('clearLogBtn')
         ?.addEventListener('click', () => LogConsole.clear());
       if (App.bridge) initWithBridge();
     }
*/

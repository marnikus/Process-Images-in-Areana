/* bridge-call.js — one safe way to call Python (BUG 03.5)
   RULE18: file 150-300, func <= 30, CC <= 10

   Before: every panel wrote `if (b && b.add_url) b.add_url(v, cb);`
   A missing slot meant: no call, no callback, no log — a dead button.

   After: BridgeCall.invoke(name, args, cb)
     1. direct slot when QWebChannel exposed it
     2. bridge.invoke(name, argsJson) fallback (see app/ui/bridge_slots.py)
     3. otherwise a visible error — never a silent no-op
*/
'use strict';

window.BridgeCall = {
  _pending: [],
  _missing: new Set(),

  bridge() {
    return (window.App && window.App.bridge) || (window.BridgeReady && window.BridgeReady.bridge) || null;
  },

  ready() { return !!this.bridge(); },

  _report(msg, level) {
    if (typeof LogConsole !== 'undefined') LogConsole.log(msg, level || 'error');
    else console[level === 'error' ? 'error' : 'log'](msg);
  },

  /* Parse whatever Python returned into an object the caller can trust. */
  parse(res) {
    if (res === null || res === undefined) return { ok: false, error: 'no response' };
    if (typeof res === 'object') return res;
    try { return JSON.parse(res); } catch (e) { return { ok: true, value: String(res) }; }
  },

  _direct(b, name, args, done) {
    try {
      b[name](...args, (res) => done(this.parse(res)));
      return true;
    } catch (e) {
      this._report(`Bridge ${name} threw: ${e.message}`, 'error');
      done({ ok: false, error: e.message });
      return true;
    }
  },

  _fallback(b, name, args, done) {
    if (typeof b.invoke !== 'function') return false;
    if (!this._missing.has(name)) {
      this._missing.add(name);
      this._report(`⚠ Slot "${name}" not exposed — using invoke() fallback`, 'warn');
    }
    try {
      b.invoke(name, JSON.stringify(args), (res) => done(this.parse(res)));
      return true;
    } catch (e) {
      done({ ok: false, error: e.message });
      return true;
    }
  },

  /* The only call helper panels should use. cb receives a parsed object. */
  invoke(name, args, cb) {
    const list = Array.isArray(args) ? args : (args === undefined ? [] : [args]);
    const done = (obj) => { if (typeof cb === 'function') cb(obj); return obj; };
    const b = this.bridge();
    if (!b) {
      this._pending.push(() => this.invoke(name, list, cb));
      return done({ ok: false, error: 'bridge not ready — call queued', queued: true });
    }
    if (typeof b[name] === 'function') return this._direct(b, name, list, done);
    if (this._fallback(b, name, list, done)) return undefined;
    this._report(`❌ Action unavailable: bridge slot "${name}" is missing`, 'error');
    return done({ ok: false, error: `missing slot ${name}` });
  },

  /* Invoke + standard success/failure logging. Returns nothing. */
  run(name, args, opts) {
    const o = opts || {};
    this.invoke(name, args, (r) => {
      if (r.queued) return;
      if (r.ok === false) {
        this._report(`${o.failPrefix || name + ' failed'}: ${r.error || 'unknown error'}`, 'error');
        if (o.onError) o.onError(r);
        return;
      }
      if (o.success) this._report(o.success(r), 'success');
      if (o.onOk) o.onOk(r);
    });
  },

  flush() {
    const queued = this._pending.splice(0, this._pending.length);
    queued.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
  },

  /* Startup contract check — dead buttons become log lines, not mysteries. */
  audit() {
    const b = this.bridge();
    if (!b || typeof b.slot_audit !== 'function') return;
    b.slot_audit((res) => {
      const r = this.parse(res);
      if (r.missing && r.missing.length) this._report(`❌ Missing bridge slots: ${r.missing.join(', ')}`, 'error');
      else if (r.fallback_only && r.fallback_only.length) this._report(`⚠ ${r.fallback_only.length} slot(s) via invoke() fallback`, 'warn');
      else this._report(`✅ Bridge contract OK (${r.exposed ? r.exposed.length : 0} slots)`, 'success');
    });
  },
};

if (window.BridgeReady && window.BridgeReady.ready) {
  window.BridgeReady.ready(() => { window.BridgeCall.flush(); window.BridgeCall.audit(); });
}

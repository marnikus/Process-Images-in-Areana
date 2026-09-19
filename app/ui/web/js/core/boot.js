/* boot.js — panel boot helpers (2026-10-02 bugfix release).

   Why: several "dead button" bugs shared one root cause — listeners bound
   twice (a facade AND its actions module) or bound before the bridge
   existed, and slot calls that silently vanished because QWebChannel drops
   unknown method names without any log.

   Boot owns four tiny primitives every panel can use:
     Boot.onBridgeReady(fn)   — run fn(bridge) once the QWebChannel handshake
                                finished (delegates to BridgeReady; falls back
                                to DOMContentLoaded when running standalone)
     Boot.bindOnce(el, ev, fn, key) — addEventListener exactly once per
                                element+event+key, even if init() runs twice
     Boot.needBridge(slot)    — the bridge slot function, or null + ONE console
                                warning per missing slot (never silent)
     Boot.bootPanels(names)   — init() each named panel once, errors isolated

   Deliberately NOT a `window.App` definition: arena-app.js owns `const App`;
   a second App object here would shadow it (lexical const vs window prop). */
'use strict';

window.Boot = {
  _bound: new WeakMap(),      // el → Set("ev:key")
  _warned: new Set(),         // slot names already reported
  _booted: new Set(),         // panel names already init()ed

  _app() { return (typeof App !== 'undefined') ? App : window.App; },
  _bridge() { const a = this._app(); return a ? (a.bridge || null) : null; },

  onBridgeReady(fn) {
    const br = window.BridgeReady;
    if (br && typeof br.ready === 'function') { br.ready(fn); return; }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => fn(this._bridge()), { once: true });
      return;
    }
    fn(this._bridge());
  },

  _tagSet(el) {
    let set = this._bound.get(el);
    if (!set) { set = new Set(); this._bound.set(el, set); }
    return set;
  },

  bindOnce(el, ev, fn, key) {
    if (!el || typeof fn !== 'function') return false;
    const tag = `${ev}:${key || fn.name || 'anon'}`;
    const set = this._tagSet(el);
    if (set.has(tag)) return false;
    set.add(tag);
    el.addEventListener(ev, fn);
    return true;
  },

  bindOnceById(id, ev, fn, key) {
    return this.bindOnce(document.getElementById(id), ev, fn, key || id);
  },

  _warnMissing(slot, connected) {
    if (this._warned.has(slot)) return;
    this._warned.add(slot);
    console.warn(`[Boot] bridge slot missing: ${slot} (${connected ? 'not registered' : 'bridge not connected'})`);
    if (connected && typeof LogConsole !== 'undefined') LogConsole.log(`UI→bridge slot missing: ${slot}`, 'warn');
  },

  needBridge(slot) {
    const b = this._bridge();
    const fn = b && b[slot];
    if (typeof fn === 'function') return fn.bind(b);
    this._warnMissing(slot, !!b);
    return null;
  },

  _initPanel(name) {
    const obj = window[name];
    if (!obj || typeof obj.init !== 'function') return;
    this._booted.add(name);
    try { obj.init(); } catch (e) { console.error(`[Boot] ${name}.init failed`, e); }
  },

  bootPanels(names) {
    (names || []).forEach((name) => { if (!this._booted.has(name)) this._initPanel(name); });
  },

  _reset() { this._warned.clear(); this._booted.clear(); },
};

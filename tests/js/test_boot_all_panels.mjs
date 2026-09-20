/**
 * Whole-page boot smoke — loads EVERY <script> from index.html in page order into
 * one V8 sandbox, fires DOMContentLoaded with a fake QWebChannel, and asserts that
 * every panel in _PANEL_INITS actually initialises and the Browse button reaches
 * the bridge.
 *
 * Regression (2026-10-03): panels are top-level `const`s (lexical globals, not
 * window.X); Boot.bootPanels resolved them through window[name], so only the 3
 * panels that exported themselves ever ran init() — 14 panels of dead buttons.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');

// fake_dom's El is intentionally tiny; the page's init() paths need a few more no-ops.
El.prototype.setAttribute ||= function (k, v) { (this._attrs ||= {})[k] = String(v); };
El.prototype.getAttribute ||= function (k) { return (this._attrs || {})[k] ?? null; };
El.prototype.querySelector ||= () => null;
El.prototype.querySelectorAll ||= () => [];
El.prototype.closest ||= () => null;
El.prototype.focus ||= () => {};

function pageScripts() {
  const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  return [...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map((m) => m[1]).filter((s) => !s.startsWith('qrc:'));
}

/* Every bridge member is BOTH callable (slot → JSON reply) and connectable (signal). */
function fakeBridge(calls) {
  const cache = {};
  return new Proxy({}, {
    get(_t, k) {
      if (typeof k !== 'string') return undefined;
      if (!cache[k]) {
        const fn = (...args) => {
          calls.push(k);
          const cb = args.find((a) => typeof a === 'function');
          if (cb) cb(JSON.stringify(k === 'get_action_blocks' ? [] : {}));
        };
        fn.connect = () => {}; fn.disconnect = () => {};
        cache[k] = fn;
      }
      return cache[k];
    },
  });
}

function bootPage() {
  const byId = new Map();
  const anyEl = (id) => {
    if (!byId.has(id)) { const e = new El('div'); e.id = id; e.value = ''; byId.set(id, e); }
    return byId.get(id);
  };
  const docListeners = {};
  const errors = [];
  const warnings = [];
  const calls = [];
  const sb = {
    console: { log() {}, info() {}, debug() {}, warn: (...a) => warnings.push(a.join(' ')), error: (...a) => errors.push(a.map(String).join(' ')) },
    JSON, Set, WeakMap, Map, Object, Array, String, Number, Boolean, Error, Promise, Date, Math, RegExp,
    parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {}, requestAnimationFrame: () => 1,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    getComputedStyle: () => ({ display: 'block' }),
    MutationObserver: class { observe() {} disconnect() {} },
    ResizeObserver: class { observe() {} disconnect() {} },
    navigator: { clipboard: { writeText: async () => {} } },
    location: { href: 'file:///index.html', search: '' }, innerWidth: 1600, innerHeight: 1000,
    addEventListener: () => {}, removeEventListener() {},
    CustomEvent: class { constructor(t, o) { this.type = t; Object.assign(this, o || {}); } },
    Event: class { constructor(t) { this.type = t; } },
    document: {
      readyState: 'loading', body: new El('body'), documentElement: new El('html'), head: new El('head'),
      getElementById: anyEl, querySelector: () => null, querySelectorAll: () => [],
      createElement: (t) => new El(t), createTextNode: (t) => ({ textContent: t }),
      addEventListener: (t, f) => { (docListeners[t] ||= []).push(f); }, removeEventListener() {}, dispatchEvent() {},
    },
    qt: { webChannelTransport: {} },
  };
  sb.window = sb; sb.self = sb; sb.globalThis = sb;
  const bridge = fakeBridge(calls);
  sb.QWebChannel = function (_transport, cb) { cb({ objects: { bridge, captchaRecordings: bridge } }); };
  vm.createContext(sb);
  const loadErrors = [];
  for (const s of pageScripts()) {
    try { vm.runInContext(fs.readFileSync(path.join(WEB, s), 'utf8'), sb, { filename: s }); } catch (e) { loadErrors.push(`${s}: ${e.message}`); }
  }
  sb.document.readyState = 'complete';
  for (const f of docListeners.DOMContentLoaded || []) f();
  return { sb, anyEl, calls, errors, warnings, loadErrors };
}

describe('whole-page boot (index.html script order)', () => {
  test('every script loads and EVERY panel in _PANEL_INITS initialises without throwing', () => {
    const { sb, errors, loadErrors } = bootPage();
    assert.deepEqual(loadErrors, []);
    // spread → host-realm arrays (vm-realm Arrays fail deepEqual's prototype check)
    const expected = [...vm.runInContext('_PANEL_INITS', sb)];
    const booted = [...vm.runInContext('Array.from(Boot._booted)', sb)];
    assert.ok(expected.length >= 15, `registry too small: ${expected}`);
    assert.deepEqual(expected.filter((n) => !booted.includes(n)), [], 'panels never init()ed');
    assert.deepEqual(errors.filter((e) => /init failed|panel not found/.test(e)), []);
  });

  test('window.App is the lexical App and carries the bridge', () => {
    const { sb } = bootPage();
    assert.equal(vm.runInContext('window.App === App', sb), true);
    assert.equal(vm.runInContext('App.bridge !== null && App.ready === true', sb), true);
  });

  test('Browse click reaches bridge.pick_folder exactly once', () => {
    const { anyEl, calls } = bootPage();
    assert.equal((anyEl('folderPickBtn')._listeners.click || []).length, 1);
    anyEl('folderPickBtn').dispatch('click', {});
    assert.equal(calls.filter((c) => c === 'pick_folder').length, 1);
  });

  test('every published panel name resolves through Boot.panel without warnings', () => {
    const { sb, warnings } = bootPage();
    const expected = [...vm.runInContext('_PANEL_INITS', sb)];
    for (const name of expected) assert.equal(typeof sb.Boot.panel(name), 'object', name);
    assert.deepEqual(warnings.filter((w) => w.includes('panel not found')), []);
  });
});

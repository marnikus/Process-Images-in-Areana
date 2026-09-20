/**
 * Whole-page harness: loads EVERY <script> from index.html (page order) into one
 * V8 sandbox with a fake QWebChannel, fires DOMContentLoaded and hands back:
 *   emit(signal, ...args)  — fire a bridge signal into the page's handlers
 *   flushTimers()          — run every pending setTimeout callback (debounces)
 *   calls                  — [{slot, args}] every bridge slot invocation
 *   logs                   — LogConsole lines as "level: message"
 *   errors                 — console.error lines
 *   anyEl(id)              — the page's element for an id (created on demand)
 *
 * `replies[slot]` is the JSON (object or function(...args) → string) a slot
 * answers with; `prepare(anyEl)` lets a test pre-shape elements before boot.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const WEB = path.resolve(__dirname, '../../app/ui/web');

El.prototype.setAttribute ||= function (k, v) { (this._attrs ||= {})[k] = String(v); };
El.prototype.getAttribute ||= function (k) { return (this._attrs || {})[k] ?? null; };
El.prototype.focus ||= () => {};

export function pageScripts() {
  const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
  return [...html.matchAll(/<script src="([^"]+)"><\/script>/g)].map((m) => m[1]).filter((s) => !s.startsWith('qrc:'));
}

function fakeBridge(handlers, replies, calls) {
  const cache = {};
  return new Proxy({}, {
    get(_t, k) {
      if (typeof k !== 'string') return undefined;
      if (!cache[k]) {
        const fn = (...args) => {
          const cb = args.find((a) => typeof a === 'function');
          calls.push({ slot: k, args: args.filter((a) => typeof a !== 'function') });
          if (!cb) return;
          const reply = replies[k];
          cb(typeof reply === 'function' ? reply(...args) : JSON.stringify(reply ?? {}));
        };
        fn.connect = (h) => { (handlers[k] ||= []).push(h); };
        fn.disconnect = () => {};
        cache[k] = fn;
      }
      return cache[k];
    },
  });
}

export function bootPage({ replies = {}, prepare = null } = {}) {
  const byId = new Map();
  const anyEl = (id) => {
    if (!byId.has(id)) { const e = new El('div'); e.id = id; e.value = ''; byId.set(id, e); }
    return byId.get(id);
  };
  if (prepare) prepare(anyEl);
  const docListeners = {};
  const errors = [];
  const timers = [];
  const handlers = {};
  const logs = [];
  const calls = [];
  const allReplies = { get_action_blocks: [], get_undo_history: { history: [], index: -1 }, get_app_state: {}, ...replies };
  const sb = {
    console: { log() {}, info() {}, debug() {}, warn() {}, error: (...a) => errors.push(a.map(String).join(' ')) },
    JSON, Set, WeakMap, Map, Object, Array, String, Number, Boolean, Error, Promise, Date, Math, RegExp,
    parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent, encodeURI, decodeURI,
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    clearTimeout() {}, setInterval: () => 1, clearInterval() {}, requestAnimationFrame: () => 1,
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
  const bridge = fakeBridge(handlers, allReplies, calls);
  sb.QWebChannel = function (_transport, cb) { cb({ objects: { bridge, captchaRecordings: bridge } }); };
  vm.createContext(sb);
  for (const s of pageScripts()) vm.runInContext(fs.readFileSync(path.join(WEB, s), 'utf8'), sb, { filename: s });
  sb.document.readyState = 'complete';
  for (const f of docListeners.DOMContentLoaded || []) f();
  const LogConsole = vm.runInContext('LogConsole', sb);   // lexical const in the page
  const origLog = LogConsole.log.bind(LogConsole);
  LogConsole.log = (m, l) => { logs.push(`${l || 'info'}: ${m}`); return origLog(m, l); };
  const emit = (signal, ...args) => {
    const hs = handlers[signal] || [];
    assert.ok(hs.length >= 1, `no handler connected for ${signal}`);
    hs.forEach((h) => h(...args));
  };
  const flushTimers = () => { const pending = timers.splice(0); pending.forEach((t) => t.fn()); return pending.length; };
  const run = (code) => vm.runInContext(code, sb);
  return { sb, anyEl, errors, logs, calls, emit, flushTimers, handlers, run };
}

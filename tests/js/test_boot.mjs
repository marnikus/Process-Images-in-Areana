/**
 * boot.js — panel boot primitives (2026-10-02 bugfix release).
 * Runs the real file in a vm sandbox with a tiny fake document.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BOOT = path.resolve(__dirname, '../../app/ui/web/js/core/boot.js');

function load({ bridgeReady = null, readyState = 'complete', App = undefined } = {}) {
  const byId = {};
  const domListeners = {};
  const warnings = [];
  const logs = [];
  const sandbox = {
    console: { warn: (...a) => warnings.push(a.join(' ')), error: (...a) => warnings.push('E:' + a.join(' ')), log() {} },
    JSON, Set, WeakMap, Map, Object, Array, String,
    document: {
      readyState,
      getElementById: (id) => byId[id] || null,
      addEventListener: (t, fn) => { (domListeners[t] = domListeners[t] || []).push(fn); },
    },
    LogConsole: { log: (m, l) => logs.push([m, l]) },
  };
  sandbox.window = sandbox;
  if (bridgeReady) sandbox.BridgeReady = bridgeReady;
  if (App !== undefined) sandbox.App = App;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BOOT, 'utf-8'), sandbox, { filename: 'boot.js' });
  return { Boot: sandbox.window.Boot, byId, domListeners, warnings, logs, sandbox };
}

describe('Boot.bindOnce', () => {
  test('binds one listener per element+event+key even when init runs twice', () => {
    const { Boot } = load();
    const el = new El('button');
    const calls = [];
    const fn = () => calls.push(1);
    assert.equal(Boot.bindOnce(el, 'click', fn, 'k'), true);
    assert.equal(Boot.bindOnce(el, 'click', () => calls.push(2), 'k'), false);   // same key → skipped
    assert.equal(Boot.bindOnce(el, 'click', () => calls.push(3), 'other'), true); // other key → bound
    el.dispatch('click', {});
    assert.deepEqual(calls, [1, 3]);
    assert.equal(Boot.bindOnce(null, 'click', fn), false);
    assert.equal(Boot.bindOnce(el, 'click', 'not a fn'), false);
  });

  test('bindOnceById resolves through document and uses the id as key', () => {
    const { Boot, byId } = load();
    byId.addBtn = new El('button');
    let n = 0;
    assert.equal(Boot.bindOnceById('addBtn', 'click', () => n++), true);
    assert.equal(Boot.bindOnceById('addBtn', 'click', () => n++), false);
    assert.equal(Boot.bindOnceById('missing', 'click', () => n++), false);
    byId.addBtn.dispatch('click', {});
    assert.equal(n, 1);
  });
});

describe('Boot.needBridge', () => {
  test('returns a bound slot, warns ONCE per missing slot, distinguishes disconnected', () => {
    const bridge = { add_url(u, cb) { return this.tag + u; }, tag: 'B:' };
    const { Boot, warnings, logs } = load({ App: { bridge } });
    const add = Boot.needBridge('add_url');
    assert.equal(add('x'), 'B:x');                      // `this` stays the bridge
    assert.equal(Boot.needBridge('nope'), null);
    assert.equal(Boot.needBridge('nope'), null);
    assert.equal(warnings.filter((w) => w.includes('nope')).length, 1);
    assert.equal(logs.length, 1);                        // surfaced in the in-app console too
    assert.match(warnings[0], /not registered/);

    const off = load({ App: { bridge: null } });
    assert.equal(off.Boot.needBridge('add_url'), null);
    assert.match(off.warnings[0], /bridge not connected/);
    assert.equal(off.logs.length, 0);                    // no LogConsole spam before the bridge exists
  });
});

describe('Boot.bootPanels', () => {
  test('inits each panel once and isolates a throwing init', () => {
    const { Boot, sandbox, warnings } = load();
    const order = [];
    sandbox.window.A = { init() { order.push('A'); } };
    sandbox.window.B = { init() { throw new Error('B down'); } };
    sandbox.window.C = { init() { order.push('C'); } };
    sandbox.window.D = { noInit: true };
    Boot.bootPanels(['A', 'B', 'C', 'D', 'Missing']);
    Boot.bootPanels(['A', 'C']);                          // second boot pass → no double init
    assert.deepEqual(order, ['A', 'C']);
    assert.ok(warnings.some((w) => w.includes('B.init failed')));
    // 2026-10-03: a panel that never published itself (lexical const) is reported, not skipped
    assert.equal(warnings.filter((w) => w.includes('panel not found on window: Missing')).length, 1);
    Boot.bootPanels(['Missing']);                         // warned once, not per pass
    assert.equal(warnings.filter((w) => w.includes('panel not found on window: Missing')).length, 1);
    Boot._reset();
    Boot.bootPanels(['A']);
    assert.deepEqual(order, ['A', 'C', 'A']);
  });
});

describe('Boot.onBridgeReady', () => {
  test('delegates to BridgeReady.ready when present (single handshake)', () => {
    const readyFns = [];
    const { Boot } = load({ bridgeReady: { ready: (fn) => readyFns.push(fn) } });
    let got = 'unset';
    Boot.onBridgeReady((b) => { got = b; });
    assert.equal(readyFns.length, 1);
    readyFns[0]({ slot() {} });
    assert.equal(typeof got.slot, 'function');
  });

  test('standalone: waits for DOMContentLoaded while loading, runs immediately otherwise', () => {
    const loading = load({ readyState: 'loading', App: { bridge: null } });
    let calls = 0;
    loading.Boot.onBridgeReady(() => calls++);
    assert.equal(calls, 0);
    loading.domListeners.DOMContentLoaded[0]();
    assert.equal(calls, 1);

    const done = load({ readyState: 'complete', App: { bridge: { x: 1 } } });
    let seen = null;
    done.Boot.onBridgeReady((b) => { seen = b; });
    assert.deepEqual(seen, { x: 1 });
  });
});

describe('Boot.onBridgeReady guards', () => {
  test('a non-function warns and never throws or delegates', () => {
    let delegated = 0;
    const { Boot, warnings } = load({ bridgeReady: { ready: () => delegated++ } });
    for (const bad of [undefined, null, 'fn', 42, {}]) Boot.onBridgeReady(bad);
    assert.equal(delegated, 0);
    assert.equal(warnings.filter((w) => w.includes('onBridgeReady needs a function')).length, 5);
  });
});

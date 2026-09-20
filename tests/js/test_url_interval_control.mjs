/**
 * Tier A — url-list/interval.js, the D-12R control for the URL reconcile interval.
 * The setting ships with its control: the input reads the pushed
 * `progress_updated.live.url_interval_ms` (no getter slot exists, D-20) and Save
 * clamps 500…60000 before calling the existing `save_settings` slot.
 * Real module in a vm sandbox with a fake document + a counting fake bridge.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const webJs = path.resolve(__dirname, '../../app/ui/web/js');
const modulePath = path.resolve(webJs, 'panels/url-list/interval.js');
const bootPath = path.resolve(webJs, 'core/boot.js');

function fakeInput() {
  const el = { value: '', listeners: {}, tagName: 'INPUT' };
  el.addEventListener = (ev, fn) => { (el.listeners[ev] ||= []).push(fn); };
  el.click = () => (el.listeners.click || []).forEach((fn) => fn({ preventDefault() {} }));
  return el;
}

function load({ bridge = null } = {}) {
  const els = { urlIntervalMs: fakeInput(), urlIntervalSaveBtn: fakeInput() };
  const calls = [];
  const proxyBridge = bridge && new Proxy(bridge, {
    get(target, prop) {
      if (typeof target[prop] === 'function') {
        return (...args) => { calls.push([prop, ...args]); return target[prop](...args); };
      }
      return target[prop];
    },
  });
  const sandbox = {
    console, JSON, Math, Object, Array, Map, Set, Error, Number, parseInt, isNaN, WeakMap,
    document: { getElementById: (id) => els[id] || null, readyState: 'complete', addEventListener() {} },
    App: { bridge: proxyBridge },
    LogConsole: { log: () => {} },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(bootPath, 'utf-8'), sandbox, { filename: 'boot.js' });
  vm.runInContext(fs.readFileSync(modulePath, 'utf-8'), sandbox, { filename: 'interval.js' });
  return { sandbox, els, calls, UrlInterval: sandbox.UrlInterval };
}

function fakeBridge() {
  return {
    saved: [],
    save_settings(json, cb) { this.saved.push(JSON.parse(json)); if (cb) cb(JSON.stringify({ ok: true })); },
    progress_updated: { connect() {} },
  };
}

describe('UrlInterval (D-12R)', () => {
  test('save clamps and calls save_settings with the one key', () => {
    const bridge = fakeBridge();
    const { UrlInterval, els } = load({ bridge });
    UrlInterval.init();
    els.urlIntervalMs.value = '99999';
    els.urlIntervalSaveBtn.click();
    assert.deepEqual(bridge.saved, [{ url_reconcile_interval_ms: 60000 }]);
    assert.equal(els.urlIntervalMs.value, 60000);   // the input shows what was actually saved
  });

  test('save rejects garbage and falls back to 5000; the floor is 500', () => {
    const bridge = fakeBridge();
    const { UrlInterval, els } = load({ bridge });
    UrlInterval.init();
    els.urlIntervalMs.value = 'soon';
    els.urlIntervalSaveBtn.click();
    els.urlIntervalMs.value = '12';
    els.urlIntervalSaveBtn.click();
    assert.deepEqual(bridge.saved.map((s) => s.url_reconcile_interval_ms), [5000, 500]);
    assert.equal(UrlInterval.clamp(undefined), 5000);
    assert.equal(UrlInterval.clamp(2500), 2500);
  });

  test('load repopulates from the pushed payload with no bridge call', () => {
    const bridge = fakeBridge();
    const { UrlInterval, els, calls } = load({ bridge });
    UrlInterval.load({ url_interval_ms: 1200 });
    assert.equal(els.urlIntervalMs.value, 1200);
    UrlInterval.load({});                            // nothing pushed ⇒ nothing changes
    assert.equal(els.urlIntervalMs.value, 1200);
    assert.deepEqual(calls.filter(([name]) => name !== 'progress_updated'), []);
  });

  test('it publishes itself on window (global-name contract)', () => {
    const { sandbox } = load();
    assert.equal(typeof sandbox.window.UrlInterval, 'object');
    assert.equal(typeof sandbox.window.UrlInterval.init, 'function');
  });

  test('init binds the save button exactly once', () => {
    const bridge = fakeBridge();
    const { UrlInterval, els } = load({ bridge });
    UrlInterval.init();
    UrlInterval.init();
    assert.equal((els.urlIntervalSaveBtn.listeners.click || []).length, 1);
    els.urlIntervalMs.value = '3000';
    els.urlIntervalSaveBtn.click();
    assert.equal(bridge.saved.length, 1);
  });

  test('the frozen url-list files did not grow (D-24a early warning)', () => {
    const baseline = { 'listeners.js': 63, 'cooldown.js': 49, 'actions.js': 167, 'store.js': 39, 'matching.js': 106, '../url-list.js': 138 };
    for (const [file, lines] of Object.entries(baseline)) {
      const src = fs.readFileSync(path.resolve(webJs, 'panels/url-list', file), 'utf-8');
      assert.equal(src.split('\n').length, lines, `${file} grew — new behaviour belongs in a new file`);
    }
  });
});

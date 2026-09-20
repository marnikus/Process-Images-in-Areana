/**
 * Tier A — url-list/interval.js: the D-12R cadence control (Node.js, no browser).
 * Real boot.js + real interval.js in a vm sandbox; fake document elements and bridge.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BOOT = path.resolve(__dirname, '../../app/ui/web/js/core/boot.js');
const MOD = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list/interval.js');

function load({ inputValue = '5000' } = {}) {
  const bridgeCalls = [];
  const liveConnects = [];
  const listeners = {};
  const input = { value: inputValue };
  const button = {
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
    click: () => { (listeners.click || []).forEach((fn) => fn()); },
  };
  const byId = { urlIntervalMs: input, urlIntervalSaveBtn: button };
  const sandbox = {
    console, JSON, Math, Object, Array, String, parseInt, isNaN,
    document: {
      readyState: 'complete',
      getElementById: (id) => byId[id] || null,
      addEventListener: () => {},
    },
    App: { bridge: {
      save_settings: (payload, cb) => { bridgeCalls.push(payload); if (cb) cb('{"ok": true}'); },
      progress_updated: { connect: (fn) => liveConnects.push(fn) },
    } },
    LogConsole: { log: () => {} },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(BOOT, 'utf-8'), sandbox, { filename: 'boot.js' });
  vm.runInContext(fs.readFileSync(MOD, 'utf-8'), sandbox, { filename: 'interval.js' });
  return { UrlInterval: sandbox.window.UrlInterval, input, button,
           bridgeCalls, liveConnects, listeners };
}

describe('url interval control', () => {
  test('save clamps and calls save_settings', () => {
    const t = load({ inputValue: '99999' });
    t.UrlInterval.init();
    t.button.click();
    assert.deepEqual(t.bridgeCalls, ['{"url_reconcile_interval_ms":60000}']);
  });

  test('save rejects garbage and falls back to 5000', () => {
    const t = load({ inputValue: 'abc' });
    t.UrlInterval.init();
    t.button.click();
    assert.deepEqual(t.bridgeCalls, ['{"url_reconcile_interval_ms":5000}']);
  });

  test('load repopulates from the pushed payload', () => {
    const t = load({ inputValue: '5000' });
    t.UrlInterval.load({ url_interval_ms: 1200 });
    assert.equal(t.input.value, 1200);
    assert.deepEqual(t.bridgeCalls, []);  // push only: no bridge round-trip
  });

  test('it publishes itself', () => {
    const t = load();
    assert.equal(typeof t.UrlInterval, 'object');
    assert.equal(t.UrlInterval.MIN_MS, 500);
  });

  test('init binds the save button exactly once', () => {
    const t = load();
    t.UrlInterval.init();
    t.UrlInterval.init();
    assert.equal(t.listeners.click.length, 1);
    assert.equal(t.liveConnects.length, 1);
  });

  test('the frozen url-list files did not grow', () => {
    const base = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list');
    const counts = {};
    for (const f of ['listeners', 'cooldown', 'actions', 'store', 'matching']) {
      const text = fs.readFileSync(path.resolve(base, f + '.js'), 'utf-8');
      counts[f] = text.split('\n').length - 1;
    }
    const main = fs.readFileSync(path.resolve(base, '../url-list.js'), 'utf-8');
    counts['url-list.js'] = main.split('\n').length - 1;
    assert.deepEqual(counts, { listeners: 62, cooldown: 48, actions: 166,
      store: 38, matching: 105, 'url-list.js': 137 });
  });
});

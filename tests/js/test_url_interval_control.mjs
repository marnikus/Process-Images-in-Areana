/**
 * Tier A — UrlInterval control tests (harness A, module sandbox; plan §S6 tests 24-29).
 * RED at base: app/ui/web/js/panels/url-list/interval.js does not exist (ENOENT).
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const modulePath = path.resolve(__dirname, '../../app/ui/web/js/panels/url-list/interval.js');

function makeSandbox({ typed = '5000' } = {}) {
  const bridgeCalls = [];
  const listeners = [];
  const elements = {
    urlIntervalMs: { value: typed },
    urlIntervalSaveBtn: { disabled: false, textContent: 'Save' },
  };
  const bridgeProxy = new Proxy({}, {
    get(_t, prop) {
      if (prop === 'connect') return () => {};
      return (payload, cb) => bridgeCalls.push([prop, payload, cb]);
    },
  });
  const sandbox = {
    console, JSON, Math, Object, Number, isNaN,
    parseInt, parseFloat,
    window: {
      App: { bridge: bridgeProxy },
      Boot: {
        bindOnceById: (id, ev, fn) => {
          const tag = `${ev}:${id}`;                    // mirrors core/boot.js bindOnce semantics
          if (sandbox.__tags.has(tag)) return;
          sandbox.__tags.add(tag);
          listeners.push([id, ev]);
        },
        onBridgeReady: (fn) => { sandbox.__ready = fn; },
      },
      progress_updated: { connect(fn) { sandbox.__connect_live = fn; } },
    },
    document: { getElementById: (id) => elements[id] ?? null },
    navigator: {},
  };
  sandbox.__tags = new Set();
  sandbox.self = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(modulePath, 'utf-8'), sandbox, { filename: 'interval.js' });
  return { sandbox, elements, bridgeCalls, listeners };
}

describe('UrlInterval (D-12R interval control)', () => {
  test('publishes itself on window (I-35)', () => {
    const { sandbox } = makeSandbox();
    assert.ok(sandbox.window.UrlInterval, 'window.UrlInterval must exist');
    assert.equal(sandbox.window.UrlInterval.DEFAULT_MS, 5000);
    assert.equal(sandbox.window.UrlInterval.MIN_MS, 500);
    assert.equal(sandbox.window.UrlInterval.MAX_MS, 60000);
  });

  test('load repopulates from the pushed payload with no bridge call', () => {
    const { sandbox, elements, bridgeCalls } = makeSandbox({ typed: '5000' });
    sandbox.window.UrlInterval.load({ url_interval_ms: 1200 });
    assert.equal(elements.urlIntervalMs.value, 1200);
    assert.equal(bridgeCalls.length, 0, 'load must not round-trip the bridge');
  });

  test('init binds the save button exactly once and hooks bridge ready', () => {
    const { sandbox, listeners } = makeSandbox();
    sandbox.window.UrlInterval.init();
    sandbox.window.UrlInterval.init();
    sandbox.__ready();                                  // Bridge-ready: live wire starts
    assert.deepEqual(listeners, [['urlIntervalSaveBtn', 'click']]);
    assert.equal(typeof sandbox.__ready, 'function');
  });

  test('save clamps to the configured bounds and calls save_settings', () => {
    const { sandbox, elements, bridgeCalls } = makeSandbox({ typed: '99999' });
    elements.__ = 0;
    sandbox.window.UrlInterval.save();
    const [, payload] = bridgeCalls.find(([slot]) => slot === 'save_settings') || [];
    assert.ok(payload, 'save_settings must be called');
    assert.deepEqual(JSON.parse(payload), { url_reconcile_interval_ms: 60000 });
    assert.equal(elements.urlIntervalMs.value, 60000);
  });

  test('save rejects garbage and falls back to 5000', () => {
    const { sandbox, elements, bridgeCalls } = makeSandbox({ typed: 'wat' });
    sandbox.window.UrlInterval.save();
    const [, payload] = bridgeCalls.find(([slot]) => slot === 'save_settings') || [];
    assert.deepEqual(JSON.parse(payload), { url_reconcile_interval_ms: 5000 });
    assert.equal(elements.urlIntervalMs.value, 5000);
  });

  test('live push wires through progress_updated.connect', () => {
    const { sandbox, elements } = makeSandbox();
    sandbox.window.UrlInterval.init();
    sandbox.__ready();                                  // onBridgeReady → _bindLive
    assert.equal(typeof sandbox.__connect_live, 'function');
    sandbox.__connect_live(JSON.stringify({ live: { url_interval_ms: 900 } }));
    assert.equal(elements.urlIntervalMs.value, 900);
  });

  test('frozen url-list files did not grow (D-24a)', () => {
    const dir = path.resolve(__dirname, '../../app/ui/web/js/panels');
    const base = {
      'url-list/listeners.js': 62,
      'url-list/cooldown.js': 48,
      'url-list/actions.js': 166,
      'url-list/store.js': 38,
      'url-list/matching.js': 105,
      'url-list.js': 137,
    };
    for (const [rel, expected] of Object.entries(base)) {
      const lines = fs.readFileSync(path.join(dir, rel), 'utf-8').split('\n').length - 1;
      assert.equal(lines, expected, `${rel} changed (${lines} != ${expected})`);
    }
  });
});

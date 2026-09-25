/**
 * bridge-ready.js — the single QWebChannel handshake + boot queue.
 * Runs the real file in a vm sandbox (standalone branch: no QWebChannel),
 * pinning the queue/flush contract and the non-callback guard.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, '../../app/ui/web/js/core/bridge-ready.js');

function load({ app } = {}) {
  const domListeners = {};
  const warnings = [];
  const sandbox = {
    console: { warn: (...a) => warnings.push(a.join(' ')), error: () => {}, log() {} },
    JSON, Object, Array, String,
    document: {
      addEventListener: (t, fn) => { (domListeners[t] = domListeners[t] || []).push(fn); },
    },
  };
  sandbox.window = sandbox;
  if (app !== undefined) sandbox.App = app;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SRC, 'utf-8'), sandbox, { filename: 'bridge-ready.js' });
  return {
    BridgeReady: sandbox.window.BridgeReady,
    fireDomReady: () => (domListeners.DOMContentLoaded || []).forEach((fn) => fn({ type: 'DOMContentLoaded' })),
    warnings,
  };
}

describe('BridgeReady', () => {
  test('queues while the handshake is open, flushes on connect', () => {
    const { BridgeReady, fireDomReady } = load();
    let got = 'unset';
    BridgeReady.ready((b) => { got = b; });
    assert.equal(got, 'unset');          // not connected yet → queued
    fireDomReady();                      // standalone: no QWebChannel → connected
    assert.equal(got, null);             // flushed with the (null) standalone bridge
    assert.equal(BridgeReady.connected, true);
  });

  test('runs immediately once connected', () => {
    const { BridgeReady, fireDomReady } = load();
    fireDomReady();
    let n = 0;
    BridgeReady.ready(() => { n++; });
    assert.equal(n, 1);
  });

  test('a non-function callback is warned about and ignored — no uncaught throw', () => {
    const { BridgeReady, fireDomReady, warnings } = load();
    fireDomReady();                      // connected: the guard must catch it BEFORE the call
    assert.doesNotThrow(() => BridgeReady.ready(undefined));
    assert.doesNotThrow(() => BridgeReady.ready({}));
    assert.ok(warnings.some((w) => w.includes('ready(callback)')));

    const open = load();                 // queued path: the guard must catch it there too
    assert.doesNotThrow(() => open.BridgeReady.ready(null));
    open.fireDomReady();                 // a bad arg must not sit in the queue and blow up later
  });
});

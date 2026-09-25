/**
 * bridge-ready.js — single QWebChannel handshake + boot queue.
 * Runs the real file in a vm sandbox with a tiny fake document.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const READY = path.resolve(__dirname, '../../app/ui/web/js/core/bridge-ready.js');

function load({ channel = null } = {}) {
  const domListeners = {};
  const warnings = [];
  const errors = [];
  const sandbox = {
    console: { warn: (...a) => warnings.push(a.join(' ')), error: (...a) => errors.push(a.join(' ')), log() {} },
    document: {
      addEventListener: (t, fn) => { (domListeners[t] = domListeners[t] || []).push(fn); },
    },
  };
  sandbox.window = sandbox;
  if (channel) {
    sandbox.qt = { webChannelTransport: {} };
    sandbox.QWebChannel = class { constructor(_t, cb) { cb(channel); } };
  }
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(READY, 'utf-8'), sandbox, { filename: 'bridge-ready.js' });
  const boot = () => domListeners.DOMContentLoaded.forEach((fn) => fn());
  return { BridgeReady: sandbox.window.BridgeReady, boot, warnings, errors };
}

describe('BridgeReady.ready', () => {
  test('queues before boot, flushes on DOMContentLoaded (standalone)', () => {
    const { BridgeReady, boot } = load();
    const seen = [];
    BridgeReady.ready((b) => seen.push(b));
    assert.equal(seen.length, 0);
    boot();
    assert.deepEqual(seen, [null]);
    assert.equal(BridgeReady.connected, true);
  });

  test('runs immediately once connected', () => {
    const bridge = { slot() {} };
    const { BridgeReady, boot } = load({ channel: { objects: { bridge } } });
    boot();
    let seen = 'unset';
    BridgeReady.ready((b) => { seen = b; });
    assert.equal(seen, bridge);
  });

  test('a non-function warns and is never queued or run', () => {
    const { BridgeReady, boot, warnings, errors } = load();
    for (const bad of [undefined, null, 'fn', 42, {}]) BridgeReady.ready(bad);
    boot();
    assert.equal(warnings.filter((w) => w.includes('ready() needs a function')).length, 5);
    assert.equal(errors.length, 0);
    assert.equal(BridgeReady.connected, true);
  });
});

/* Recording probes — Tier A, execute the REAL probe files
   (app/browser/recording_js/*) against purpose-built stubs (RULE 8).
   Verified: observer buffering + cap + idempotence, fetch/XHR wrap,
   flush drain, snapshot in-page redaction of recaptcha fields. */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const probe = (name) => readFileSync(join(ROOT, 'app', 'browser', 'recording_js', name), 'utf8').trim();

/* ——— observer.js ——— */

class FakeObserver {
  constructor(cb) { this.cb = cb; FakeObserver.instances.push(this); }
  observe(target, opts) { this.target = target; this.opts = opts; }
  fire(muts) { this.cb(muts); }
}
FakeObserver.instances = [];

function observerSandbox() {
  FakeObserver.instances = [];
  const document = { documentElement: { nodeType: 1 } };
  const window = {};
  const ctx = vm.createContext({ window, document, MutationObserver: FakeObserver });
  ctx.window = window; window.window = window;
  return { ctx, window };
}

test('observer: installs once and buffers mutation summaries', () => {
  const { ctx, window } = observerSandbox();
  assert.equal(vm.runInContext(probe('observer.js'), ctx), 'installed');
  assert.equal(vm.runInContext(probe('observer.js'), ctx), 'already-installed');
  const obs = FakeObserver.instances[0];
  assert.equal(FakeObserver.instances.length, 1);  // idempotent
  assert.ok(obs.opts.subtree && obs.opts.childList && obs.opts.attributes);
  obs.fire([
    { type: 'childList', target: { nodeType: 1, tagName: 'DIV', id: 'dlg' },
      addedNodes: [1, 2], removedNodes: [] },
    { type: 'attributes', target: { nodeType: 1, tagName: 'SPAN', className: 'x y' },
      attributeName: 'data-state' },
    { type: 'characterData', target: { nodeValue: 'hello' } },
  ]);
  const buf = window.__arenaRecMut;
  assert.equal(buf.length, 3);
  assert.equal(buf[0].mut, 'childList'); assert.equal(buf[0].sel, 'div#dlg');
  assert.equal(buf[0].added, 2); assert.equal(buf[0].removed, 0);
  assert.equal(buf[1].mut, 'attr'); assert.equal(buf[1].attr, 'data-state');
  assert.equal(buf[2].mut, 'text'); assert.equal(buf[2].len, 5);
  assert.ok(buf[0].ts);  // every entry timestamped
});

test('observer: buffer capped at 500 entries (drop-oldest)', () => {
  const { ctx, window } = observerSandbox();
  vm.runInContext(probe('observer.js'), ctx);
  const obs = FakeObserver.instances[0];
  for (let i = 0; i < 120; i++) {
    obs.fire(Array.from({ length: 60 }, () => (
      { type: 'childList', target: { nodeType: 1, tagName: 'I' }, addedNodes: [], removedNodes: [] })));
  }
  assert.equal(window.__arenaRecMut.length, 500);
});

/* ——— netwrap.js ——— */

function netSandbox() {
  const requests = [];
  const fetchImpl = async (input, init) => {
    requests.push(['fetch', input, init]);
    if (String(input).includes('boom')) { const e = new Error('net'); e.name = 'AbortError'; throw e; }
    return { status: 200 };
  };
  class XHR {
    constructor() { this.status = 201; this._listeners = {}; }
    addEventListener(ev, cb) { (this._listeners[ev] = this._listeners[ev] || []).push(cb); }
  }
  XHR.prototype.open = function (m, u) { this._opened = [m, u]; };
  XHR.prototype.send = function () { (this._listeners.loadend || []).forEach((cb) => cb()); };
  const window = { fetch: fetchImpl, XMLHttpRequest: XHR };
  const ctx = vm.createContext({ window });
  window.window = window;
  return { ctx, window, XHR, requests };
}

test('netwrap: records fetch + xhr requests without bodies', async () => {
  const { ctx, window, XHR } = netSandbox();
  assert.equal(vm.runInContext(probe('netwrap.js'), ctx), 'installed');
  assert.equal(vm.runInContext(probe('netwrap.js'), ctx), 'already-installed');
  await window.fetch('https://arena.ai/api/chat', { method: 'post' });
  const xhr = new XHR();
  xhr.open('GET', 'https://arena.ai/api/models');
  xhr.send();
  const buf = window.__arenaRecNet;
  assert.equal(buf.length, 2);
  assert.equal(buf[0].via, 'fetch'); assert.equal(buf[0].method, 'POST');
  assert.equal(buf[0].url, 'https://arena.ai/api/chat'); assert.equal(buf[0].status, 200);
  assert.equal(buf[1].via, 'xhr'); assert.equal(buf[1].method, 'GET');
  assert.equal(buf[1].status, 201);
});

test('netwrap: failed fetch still logged with status 0', async () => {
  const { ctx, window } = netSandbox();
  vm.runInContext(probe('netwrap.js'), ctx);
  await assert.rejects(window.fetch('https://arena.ai/boom'));
  const buf = window.__arenaRecNet;
  assert.equal(buf.length, 1);
  assert.equal(buf[0].status, 0); assert.equal(buf[0].error, 'AbortError');
});

/* ——— flush.js ——— */

test('flush: drains both buffers and clears them', () => {
  const window = { __arenaRecMut: [{ kind: 'mutation' }, { kind: 'mutation' }],
                   __arenaRecNet: [{ kind: 'network' }] };
  const ctx = vm.createContext({ window });
  const res = vm.runInContext(probe('flush.js'), ctx);
  assert.equal(res.mutations.length, 2); assert.equal(res.requests.length, 1);
  assert.equal(window.__arenaRecMut.length, 0);
  assert.equal(window.__arenaRecNet.length, 0);
  const again = vm.runInContext(probe('flush.js'), ctx);
  assert.equal(again.mutations.length, 0);
});

/* ——— snapshot.js ——— */

test('snapshot: redacts recaptcha fields IN THE PAGE before returning', () => {
  const secret = { tagName: 'TEXTAREA', value: 'TOKEN-SECRET-123', textContent: 'TOKEN-SECRET-123' };
  const cloneRoot = {
    querySelectorAll: () => [secret],
    outerHTML: '<html><textarea name="g-recaptcha-response">TOKEN-SECRET-123</textarea></html>',
  };
  const document = { documentElement: { cloneNode: () => cloneRoot } };
  const ctx = vm.createContext({ document });
  const res = vm.runInContext(probe('snapshot.js'), ctx);
  assert.equal(res.ok, true);
  assert.equal(res.redacted, 1);
  assert.equal(secret.textContent, '[REDACTED:len=16]');  // value never leaves the page
  assert.ok(res.html.includes('<html>'));
});

test('snapshot: input-style field redacted via value attribute', () => {
  const secret = { tagName: 'INPUT', value: 'XYZ', setAttribute(k, v) { this[k] = v; } };
  const cloneRoot = { querySelectorAll: () => [secret], outerHTML: '<html></html>' };
  const document = { documentElement: { cloneNode: () => cloneRoot } };
  const ctx = vm.createContext({ document });
  const res = vm.runInContext(probe('snapshot.js'), ctx);
  assert.equal(res.redacted, 1);
  assert.equal(secret.value, '[REDACTED:len=3]');
});

test('snapshot: probe error returns ok:false, never throws', () => {
  const document = { documentElement: { cloneNode: () => { throw new Error('dom gone'); } } };
  const ctx = vm.createContext({ document });
  const res = vm.runInContext(probe('snapshot.js'), ctx);
  assert.equal(res.ok, false);
  assert.ok(res.error.includes('dom gone'));
});

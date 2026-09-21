/**
 * run-badge.js — the run-cycle badge (D-1/D-2) and the worker number `#n` (D-3).
 *
 * Running is the quiet default; PAUSED / STOPPING / STOPPED are loud. One
 * module maps `run_state` → label/class and paints EVERY `[data-run-badge]`
 * element (one in the Run Controls title, one in the Live Debug head strip),
 * fed by the existing `progress_updated.run_state` — no new slot or signal.
 * The worker number comes from the pushed `page_pool_updated.pages[].worker_no`.
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
const readJs = (rel) => fs.readFileSync(path.join(WEB, 'js', rel), 'utf-8');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf-8');

function boot({ withBridge = true, badges = 2 } = {}) {
  const els = Array.from({ length: badges }, () => new El('span'));
  const listeners = [];
  const bridge = { progress_updated: { connect(fn) { listeners.push(fn); } } };
  const sandbox = { console, JSON, Set, WeakMap, Map, Math, Object, Array, String, Number,
    document: { getElementById: () => null, querySelectorAll: (sel) => (sel === '[data-run-badge]' ? els : []),
      readyState: 'complete', addEventListener() {} } };
  sandbox.window = sandbox;
  sandbox.App = { bridge: withBridge ? bridge : null };
  vm.createContext(sandbox);
  vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'boot.js' });
  vm.runInContext(readJs('core/run-badge.js'), sandbox, { filename: 'run-badge.js' });
  vm.runInContext('RunBadge.init()', sandbox);
  const push = (p) => listeners.forEach((fn) => fn(JSON.stringify(p)));
  return { R: sandbox.window.RunBadge, els, listeners, push };
}

describe('run badge — running is quiet, anything else is loud', () => {
  test('the four states map to label + modifier; running hides the badge', () => {
    const { R } = boot({ withBridge: false });
    const view = (s) => JSON.parse(JSON.stringify(R.view(s)));  // vm realm → plain object
    assert.deepEqual(view('running'), { label: '', mod: '' });
    assert.deepEqual(view('paused'), { label: 'PAUSED', mod: 'paused' });
    assert.deepEqual(view('stopping'), { label: 'STOPPING', mod: 'stopping' });
    assert.deepEqual(view('idle'), { label: 'STOPPED', mod: 'stopped' });
    assert.deepEqual(view(undefined), view('idle'), 'unknown/missing reads as stopped (loud, never silent)');
  });

  test('apply paints every [data-run-badge] element and toggles visibility', () => {
    const { R, els } = boot({ withBridge: false });
    R.apply('paused');
    for (const el of els) {
      assert.equal(el.textContent, 'PAUSED');
      assert.equal(el.className, 'run-badge run-badge--paused');
      assert.equal(el.hidden, false);
    }
    R.apply('running');
    for (const el of els) assert.equal(el.hidden, true);
    assert.equal(els[0].className, 'run-badge');
    R.apply('idle');
    assert.equal(els[1].textContent, 'STOPPED');
    assert.equal(els[1].className, 'run-badge run-badge--stopped');
  });

  test('self-connects once to progress_updated and reads run_state', () => {
    const h = boot();
    assert.equal(h.listeners.length, 1);
    h.R.init();
    assert.equal(h.listeners.length, 1, 'bindOnce: a second init does not double-connect');
    h.push({ run_state: 'paused', live: {} });
    assert.equal(h.els[0].textContent, 'PAUSED');
    h.push({ run_state: 'running' });
    assert.equal(h.els[0].hidden, true);
    h.push('not json');  // malformed payload never throws
  });

  test('index.html carries exactly two badge slots: Run Controls title and Live Debug head', () => {
    const slots = [...html.matchAll(/<span class="run-badge" data-run-badge><\/span>/g)];
    assert.equal(slots.length, 2);
    const runTitle = html.slice(html.indexOf('id="winRun"'), html.indexOf('<div class="run-grid">'));
    assert.match(runTitle, /data-run-badge/);
    const liveHead = html.slice(html.indexOf('id="winLiveDebug"'), html.indexOf('id="liveWorkers"'));
    assert.match(liveHead, /data-run-badge/);
    assert.ok(html.includes('js/core/run-badge.js'), 'index.html loads the module');
    assert.match(readJs('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1], /'RunBadge'/);
    const css = fs.readFileSync(path.join(WEB, 'css', 'arena.css'), 'utf-8');
    for (const m of ['paused', 'stopping', 'stopped']) assert.match(css, new RegExp(`\\.run-badge--${m}\\b`));
  });
});

describe('worker number #n (pool join order, from the pushed snapshot)', () => {
  test('the pool table row leads with #n and the live worker line shows it', () => {
    const sandbox = { console, JSON, Object, Array, Math, Date, Number, String, parseInt, isNaN, setTimeout: () => 1, setInterval: () => 1,
      document: { getElementById: () => null } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const f of ['panels/page-pool/store.js', 'panels/page-pool/render.js', 'panels/live-debug/store.js', 'panels/live-debug/render.js']) {
      vm.runInContext(readJs(f), sandbox, { filename: f });
    }
    const p = { tab_id: 'ABCDEF0123456789XYZ', worker_no: 3, title: 'T', url: 'https://arena.ai', status: 'steady', is_connected: true, jobs_completed: 0 };
    const row = vm.runInContext('PagePoolRender._rowHtml(' + JSON.stringify(p) + ')', sandbox);
    assert.match(row, /<td[^>]*><b class="worker-no">#3<\/b> ABCDEF012345<\/td>/);
    vm.runInContext('LiveDebugStore.pool = ' + JSON.stringify({ pages: [p] }), sandbox);
    const line = vm.runInContext('LiveDebugRender.workers()', sandbox);
    assert.match(line, /<span class="live-no">#3<\/span>/);
    assert.ok(line.indexOf('live-no') < line.indexOf('live-tab'), 'the number comes first');
  });
});

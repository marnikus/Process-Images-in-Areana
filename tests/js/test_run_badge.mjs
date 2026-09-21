/**
 * run-badge.js — the run-cycle ON/OFF badge (2026-09-21 A-1…A-3) and the worker number `#n` (D-3).
 *
 * RUN CYCLE ON for every state but `idle` (paused / waiting for cooldown /
 * solving captcha are still ON); RUN CYCLE OFF only after the user stopped
 * it. Never hidden. A separate sub-label names paused / stopping / the live
 * wait reason *next to* the badge, never instead of it. One module paints
 * EVERY `[data-run-badge]` + `[data-run-sub]` pair (Run Controls title, Live
 * Debug head strip) from the existing `progress_updated` — no slot, no signal.
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
  const subs = Array.from({ length: badges }, () => new El('span'));
  const listeners = [];
  const bridge = { progress_updated: { connect(fn) { listeners.push(fn); } } };
  const byQuery = { '[data-run-badge]': els, '[data-run-sub]': subs };
  const sandbox = { console, JSON, Set, WeakMap, Map, Math, Object, Array, String, Number,
    document: { getElementById: () => null, querySelectorAll: (sel) => byQuery[sel] || [],
      readyState: 'complete', addEventListener() {} } };
  sandbox.window = sandbox;
  sandbox.App = { bridge: withBridge ? bridge : null };
  vm.createContext(sandbox);
  vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'boot.js' });
  vm.runInContext(readJs('core/run-badge.js'), sandbox, { filename: 'run-badge.js' });
  vm.runInContext('RunBadge.init()', sandbox);
  const push = (p) => listeners.forEach((fn) => fn(JSON.stringify(p)));
  return { R: sandbox.window.RunBadge, els, subs, listeners, push };
}

describe('run-cycle badge — ON / OFF, always visible (A-1…A-3)', () => {
  test('idle is OFF, every other state is ON; unknown reads as OFF', () => {
    const { R } = boot({ withBridge: false });
    const view = (s) => JSON.parse(JSON.stringify(R.view(s)));  // vm realm → plain object
    assert.deepEqual(view('idle'), { label: 'RUN CYCLE OFF', mod: 'off' });
    for (const st of ['running', 'paused', 'stopping']) assert.deepEqual(view(st), { label: 'RUN CYCLE ON', mod: 'on' }, st);
    assert.deepEqual(view(undefined), view('idle'));
    assert.deepEqual(view('garbage'), view('idle'));
  });

  test('the sub-label names paused / stopping / the live wait reason, and is empty while dispatching', () => {
    const { R } = boot({ withBridge: false });
    assert.equal(R.sub('paused', {}), 'paused');
    assert.equal(R.sub('stopping', {}), 'stopping after current');
    assert.equal(R.sub('running', { wait_reason: 'all cooling' }), 'waiting for cooldown');
    assert.equal(R.sub('running', { wait_reason: 'no tab' }), 'no usable tab');
    assert.equal(R.sub('running', { wait_reason: 'no images' }), 'queue empty');
    assert.equal(R.sub('running', { wait_reason: 'cdp down' }), 'Chrome disconnected');
    assert.equal(R.sub('running', { wait_reason: '' }), '');
    assert.equal(R.sub('running', undefined), '');
    assert.equal(R.sub('idle', { wait_reason: 'all cooling' }), '', 'OFF has no wait sub-label');
    assert.equal(R.sub('paused', { wait_reason: 'all cooling' }), 'paused', 'paused wins over the wait reason');
  });

  test('apply paints badge + sub-label on every slot and never hides the badge', () => {
    const { R, els, subs } = boot({ withBridge: false });
    R.apply('paused', { wait_reason: '' });
    for (const el of els) {
      assert.equal(el.textContent, 'RUN CYCLE ON');
      assert.equal(el.className, 'run-badge run-badge--on');
      assert.equal(el.hidden, false);
    }
    for (const el of subs) { assert.equal(el.textContent, 'paused'); assert.equal(el.hidden, false); }
    R.apply('running', { wait_reason: '' });
    for (const el of els) assert.equal(el.hidden, false, 'ON stays visible while running');
    for (const el of subs) assert.equal(el.hidden, true, 'no sub-label while dispatching');
    R.apply('idle');
    assert.equal(els[1].textContent, 'RUN CYCLE OFF');
    assert.equal(els[1].className, 'run-badge run-badge--off');
    assert.equal(els[1].hidden, false);
  });

  test('self-connects once to progress_updated and reads run_state + live.wait_reason', () => {
    const h = boot();
    assert.equal(h.listeners.length, 1);
    h.R.init();
    assert.equal(h.listeners.length, 1, 'bindOnce: a second init does not double-connect');
    h.push({ run_state: 'running', live: { wait_reason: 'all cooling' } });
    assert.equal(h.els[0].textContent, 'RUN CYCLE ON');
    assert.equal(h.subs[0].textContent, 'waiting for cooldown');
    h.push({ run_state: 'idle' });
    assert.equal(h.els[0].textContent, 'RUN CYCLE OFF');
    h.push('not json');  // malformed payload never throws
  });

  test('index.html carries two badge + sub-label pairs: Run Controls title and Live Debug head', () => {
    const slots = [...html.matchAll(/<span class="run-badge" data-run-badge><\/span><span class="run-sub" data-run-sub><\/span>/g)];
    assert.equal(slots.length, 2);
    const runTitle = html.slice(html.indexOf('id="winRun"'), html.indexOf('<div class="run-grid">'));
    assert.match(runTitle, /data-run-badge/);
    const liveHead = html.slice(html.indexOf('id="winLiveDebug"'), html.indexOf('id="liveWorkers"'));
    assert.match(liveHead, /data-run-badge/);
    assert.ok(html.includes('js/core/run-badge.js'), 'index.html loads the module');
    assert.match(readJs('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1], /'RunBadge'/);
    const css = fs.readFileSync(path.join(WEB, 'css', 'arena.css'), 'utf-8');
    for (const m of ['on', 'off']) assert.match(css, new RegExp(`\\.run-badge--${m}\\b`));
    assert.match(css, /\.run-sub\b/);
    assert.doesNotMatch(css, /\.run-badge\[hidden\]/, 'the badge is never hidden');
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

/** S8: boot the real HTML/scripts, render the grid, then click the rescued controls. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';
import { spawnSync } from 'node:child_process';
import { createSashGrid, ALL_WINDOW_IDS, TITLE_SECONDARIES } from './sash_harness.mjs';

const WEB = path.resolve('app/ui/web');
async function bootPage(t, options = {}) {
  const dom = new JSDOM(fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), {
    runScripts: 'outside-only', url: 'https://arena.test/',
  });
  t.after(() => dom.window.close());
  const w = dom.window, calls = [], warnings = [], errors = [], slots = {}, signals = {}, timers = new Map();
  let now = 2000000, timerId = 0;
  w.Date.now = () => now;
  // Wait for jsdom's automatic event before installing the real boot handlers.
  await new Promise(resolve => w.document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  w.console = { log() {}, info() {}, debug() {}, warn: (...a) => warnings.push(a.join(' ')), error: (...a) => errors.push(a.join(' ')) };
  w.setTimeout = w.requestAnimationFrame = () => 1;
  w.setInterval = (fn, ms) => { const id = ++timerId; timers.set(id, { fn, ms }); return id; };
  w.clearTimeout = w.clearInterval = () => {};
  const bridge = new Proxy({}, { get(_target, name) {
    if (!slots[name]) {
      slots[name] = (...args) => {
        calls.push({ name, args });
        const cb = args.find(a => typeof a === 'function');
        if (options.deferPool && name === 'get_page_pool_status') return;
        const replies = { get_arena_state: {progress: {live: options.initialLive || livePayload()}}, get_action_blocks: [], get_page_pool_status: { total: 0, steady: 0, busy: 0, cooling: 0, free: 0, pages: [], waits_in_scope: false } };
        cb?.(JSON.stringify(replies[name] || {}));
      };
      slots[name].connect = fn => { (signals[name] ||= []).push(fn); };
      slots[name].disconnect = () => {};
    }
    return slots[name];
  } });
  w.qt = { webChannelTransport: {} };
  w.QWebChannel = function (_transport, cb) { cb({ objects: { bridge, captchaRecordings: bridge } }); };
  for (const script of w.document.querySelectorAll('script[src]')) {
    const src = script.getAttribute('src');
    if (!src.startsWith('qrc:')) vm.runInContext(fs.readFileSync(path.join(WEB, src), 'utf8'), dom.getInternalVMContext(), { filename: src });
  }
  w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
  assert.deepEqual(errors, [], 'whole-page boot errors');
  return { w, calls, warnings, timers, advance: ms => { now += ms; },
    emit: (name, payload) => { for (const fn of signals[name] || []) fn(JSON.stringify(payload)); }, signals };
}

test('the real grid keeps winLiveDebug and its children through repeated render', async t => {
  const { w } = await bootPage(t);
  const panel = w.document.getElementById('winLiveDebug');
  assert.ok(panel, 'winLiveDebug missing');
  const body = panel.querySelector('#poolTableBody');
  for (let i = 0; i < 2; i++) {
    w.SashGrid.render();
    assert.equal(w.document.querySelector('#sashGrid .sash-window[data-win="live_debug"] > .panel'), panel);
    assert.equal(panel.querySelector('#poolTableBody'), body);
    assert.ok(panel.isConnected);
  }
});

test('all three rescued pool buttons reach the real panel actions exactly once', async t => {
  const { w, calls } = await bootPage(t);
  const panel = w.document.getElementById('winLiveDebug');
  assert.ok(panel);
  for (const id of ['poolTableBody', 'poolRefreshBtn', 'poolConnectBtn', 'poolClearBtn', 'poolStatusBadge',
                     'poolTotal', 'poolSteady', 'poolBusy', 'poolCooling', 'poolFree']) {
    assert.equal(w.document.querySelectorAll('#' + id).length, 1);
    assert.ok(panel.contains(w.document.getElementById(id)), id);
  }
  const select = w.document.getElementById('tabSelect');
  select.add(new w.Option('Tab', 'ws://test/devtools/page/t1', true, true));
  for (const [id, slot] of [['poolRefreshBtn', 'get_page_pool_status'],
                           ['poolConnectBtn', 'connect_page_pool'], ['poolClearBtn', 'clear_page_pool']]) {
    calls.length = 0;
    w.document.getElementById(id).click();
    assert.equal(calls.filter(c => c.name === slot).length, 1, id);
  }
});

test('LiveDebugPanel publishes itself and boots through the name registry', async t => {
  const { w, warnings } = await bootPage(t);
  assert.equal(w.Boot.panel('LiveDebugPanel'), w.LiveDebugPanel);
  assert.equal(typeof w.LiveDebugPanel?.init, 'function');
  assert.ok(w.Boot._booted.has('LiveDebugPanel'));
  assert.deepEqual(warnings.filter(s => /panel not found|panel for/.test(s)), []);
});

test('every built-in layout validates and mounts all sixteen windows', () => {
  const h = createSashGrid();
  assert.equal(ALL_WINDOW_IDS.length, 16);
  for (const [name, build] of Object.entries(h.SashCore.PRESETS)) {
    const tree = build();
    assert.equal(h.SashCore.validate(tree), null, name);
    assert.deepEqual([...h.SashCore.leafIds(tree)].sort(), [...ALL_WINDOW_IDS].sort(), name);
    h.SashGrid.root = tree;
    h.SashGrid.render();
    assert.ok(h.gridEl.querySelector('.sash-window[data-win="live_debug"] > .panel'), name);
  }
});

test('a v5 layout migrates without replacing user positions or sizes', () => {
  const { SashCore: S } = createSashGrid();
  const ids = ['url_list', 'folder', 'queue', 'prompt', 'run', 'progress', 'watcher', 'log',
    'settings', 'captcha', 'recordings', 'browser', 'action_blocks', 'block_config', 'arena_presets'];
  const tree = S.split('col', ids.map(S.leaf), [16, ...Array(14).fill(6)]);
  const result = S.deserialize(JSON.stringify({ v: 5, tree }));
  assert.ok(result.ok, result.error);
  assert.deepEqual(JSON.parse(JSON.stringify(result.tree.children[0])), JSON.parse(JSON.stringify(tree)));
  assert.equal(result.tree.children[1].id, 'live_debug');
  const v6 = S.serialize(result.tree);
  assert.equal(JSON.parse(v6).v, 6);
  assert.equal(S.serialize(S.deserialize(v6).tree), v6);
});

test('title fit passes with sixteen windows including the pool badge', () => {
  assert.deepEqual(TITLE_SECONDARIES.live_debug, { pre: [], post: ['poolStatusBadge'] });
  const result = spawnSync(process.execPath, ['--test', 'tests/js/test_title_fit.mjs'], { encoding: 'utf8' });
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

// S9: signals are the external boundary; actual store, renderer and buttons run.
const livePayload = () => ({ queued: 3, next_image: 'a.png', receivers: {total: 5, receivers: 2, not_receivers: 3},
  run_state: 'running', url_interval_ms: 5000, last_pass_at: 1998, passes: 4 });
const worker = (id = 't1', extra = {}) => ({ tab_id: id, title: 'Arena ' + id, url: 'https://arena.ai/' + id,
  status: 'busy', is_connected: true, current_job_id: 'job-' + id, current_image: 'a.png',
  busy_since: new Date(1910000).toISOString(), jobs_completed: 2, cooldown_remaining: 0, ...extra });
const poolPayload = pages => ({ pages, total: pages.length, steady: 0, busy: pages.length, cooling: 0, free: 0, waits_in_scope: true });

test('S9 queue head renders pushed eligibility count, first filename, receivers and run state', async t => {
  const h = await bootPage(t);
  h.emit('progress_updated', { live: livePayload() });
  const head = h.w.document.getElementById('liveDebugQueue');
  assert.ok(head, 'queue head missing');
  assert.match(head.textContent, /3 pending.*first: a.png/);
  assert.match(head.textContent, /2 receiving.*3 not receiving/);
  assert.match(head.textContent, /running/);
  h.emit('progress_updated', { live: {...livePayload(), queued: 0, next_image: ''} });
  assert.match(head.textContent, /0 pending.*queue empty/);
});

test('S9 worker rows show job identity, status, elapsed, cooldown and last-settled pause evidence', async t => {
  const h = await bootPage(t);
  const p = worker('t1', { status: 'waiting_captcha', pause: { absorbed_s: 12, cap_s: 300, remaining_s: 288 } });
  h.emit('page_pool_updated', poolPayload([p, worker('t2', {status: 'cooldown', cooldown_remaining: 30, cooldown_reason: 'job cycle'})]));
  const list = h.w.document.getElementById('liveDebugWorkers');
  assert.ok(list, 'worker list missing');
  assert.match(list.textContent, /job-t1/);
  assert.match(list.textContent, /a.png/);
  assert.match(list.textContent, /90s/);
  assert.match(list.textContent, /generation timeout paused/);
  assert.match(list.textContent, /12s absorbed.*300s cap.*288s remaining.*last settled/i);
  assert.match(list.textContent, /cooldown.*30s/);
  assert.match(list.textContent, /job cycle/);
  h.advance(5000);
  h.timers.get(h.w.LiveDebugPanel._timer).fn();
  assert.match(list.textContent, /95s/);
  assert.match(list.textContent, /cooldown.*25s/);
  assert.match(list.textContent, /288s remaining/); // NOT guessed from busy_since
});

test('S9 pool pushes replace workers including removal and empty state without a read', async t => {
  const h = await bootPage(t);
  h.calls.length = 0;
  h.emit('page_pool_updated', poolPayload([worker('t1'), worker('t2'), worker('t3')]));
  const list = h.w.document.getElementById('liveDebugWorkers');
  assert.ok(list);
  assert.equal(list.querySelectorAll('.live-debug-worker').length, 3);
  h.emit('page_pool_updated', poolPayload([worker('t2'), worker('t3')]));
  assert.equal(list.querySelectorAll('.live-debug-worker').length, 2);
  assert.doesNotMatch(list.textContent, /job-t1/);
  h.emit('page_pool_updated', poolPayload([]));
  assert.equal(list.querySelectorAll('.live-debug-worker').length, 0);
  assert.match(list.textContent, /No workers connected/);
  assert.equal(h.calls.length, 0);
});

test('S9 cadence ticker is local, read-only and bound exactly once', async t => {
  const h = await bootPage(t);
  h.emit('progress_updated', { live: livePayload() });
  const bar = h.w.document.getElementById('liveDebugCadence');
  assert.ok(bar);
  assert.match(bar.textContent, /every 5.0 s.*last pass 2s ago.*4 passes/);
  const count = h.timers.size;
  const handlers = h.signals.progress_updated.length;
  h.w.LiveDebugPanel.init();
  assert.equal(h.timers.size, count);
  assert.equal(h.signals.progress_updated.length, handlers);
  h.calls.length = 0;
  h.advance(5000);
  const timer = h.timers.get(h.w.LiveDebugPanel._timer);
  assert.equal(timer.ms, 1000);
  timer.fn();
  assert.match(bar.textContent, /last pass 7s ago/);
  assert.equal(h.calls.length, 0);
  assert.equal(bar.querySelector('input,select'), null);
  assert.equal(fs.readFileSync(path.join(WEB, 'js/arena-app/listeners.js'), 'utf8').split('\n').length, 194);
});

test('S9 Refresh calls only get_page_pool_status once; failures remain distinct from an empty pool', async t => {
  const h = await bootPage(t, { deferPool: true });
  h.emit('page_pool_updated', poolPayload([worker()]));
  const button = h.w.document.getElementById('liveDebugRefreshBtn');
  assert.ok(button);
  h.calls.length = 0;
  button.click();
  assert.deepEqual(h.calls.map(c => c.name), ['get_page_pool_status']);
  h.calls[0].args.find(a => typeof a === 'function')('{"error":"CDP unavailable"}');
  const status = h.w.document.getElementById('liveDebugStatus');
  assert.match(status.textContent, /CDP unavailable/);
  assert.match(h.w.document.getElementById('liveDebugWorkers').textContent, /job-t1/);
  h.emit('page_pool_updated', poolPayload([]));
  assert.equal(status.textContent, '');
});

test('S9 stale refresh replies cannot resurrect a removed worker', async t => {
  const h = await bootPage(t, { deferPool: true });
  const button = h.w.document.getElementById('liveDebugRefreshBtn');
  assert.ok(button);
  h.calls.length = 0;
  button.click();
  h.emit('page_pool_updated', poolPayload([]));
  h.calls[0].args.find(a => typeof a === 'function')(JSON.stringify(poolPayload([worker('stale')])));
  assert.doesNotMatch(h.w.document.getElementById('liveDebugWorkers').textContent, /stale/);
});

test('S9 untrusted labels are text, malformed updates preserve state, and OFF hides stale captcha wording', async t => {
  const h = await bootPage(t);
  h.emit('progress_updated', {live: {...livePayload(), next_image: '<img src=x onerror=alert(1)>'}});
  const list = h.w.document.getElementById('liveDebugWorkers');
  assert.ok(list);
  h.emit('page_pool_updated', {...poolPayload([worker('t1', {title: '<script>alert(1)</script>', status: 'waiting_captcha', cooldown_reason:'captcha'})]), waits_in_scope:false});
  assert.doesNotMatch(list.textContent, /captcha|solv|timeout paused/i);
  assert.equal(h.w.document.getElementById('liveDebugDetails').querySelector('script,img'), null);
  const previous = list.textContent;
  h.emit('page_pool_updated', {pages: 'bad'});
  assert.equal(list.textContent, previous);
  assert.match(h.w.document.getElementById('liveDebugStatus').textContent, /invalid|unavailable/i);
});

test('S9 missing clock is unknown rather than fabricated and uncapped clocks stay finite in the UI', async t => {
  const h = await bootPage(t);
  h.emit('page_pool_updated', poolPayload([worker('t1', {status:'waiting_captcha'})]));
  const list = h.w.document.getElementById('liveDebugWorkers');
  assert.ok(list);
  assert.match(list.textContent, /pause timing unavailable/i);
  assert.doesNotMatch(list.textContent, /90s absorbed/);
  h.emit('page_pool_updated', poolPayload([worker('t1', {status:'waiting_captcha', pause:{absorbed_s:12,cap_s:0,remaining_s:null}})]));
  assert.match(list.textContent, /uncapped/);
  assert.doesNotMatch(list.textContent, /NaN|Infinity/);
});

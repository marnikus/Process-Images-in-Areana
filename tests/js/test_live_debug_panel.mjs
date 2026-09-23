/**
 * The 16th window `live_debug` — part 1 (S8): the mount + the L-5 rescue.
 *
 * L-5: `index.html` declared `data-window="page_pool"`, an id no registry
 * knew; `SashGrid.render()` builds the grid from the registry and
 * `replaceChildren` discards everything else — the Page Pool markup was
 * destroyed by the first render. After S8 the markup lives inside the
 * registered `winLiveDebug` panel (inner ids untouched, the frozen
 * `PagePoolPanel` still binds), and the registry is one contract across
 * Python / `constants.js` / `store.js` / `_PANEL_INITS`.
 *
 * Part 2 (S9): the window's content — queue head, per-worker job lines,
 * receiver counters and the read-only cadence line, all from the two pushed
 * payloads (`progress_updated.live` + `page_pool_updated`), a local 1 s ticker
 * and zero bridge calls (D-20 / D-22); listeners.js stays frozen.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { El } from './fake_dom.mjs';
import { createSashGrid, ALL_WINDOW_IDS, panelIdOf } from './sash_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const readJs = (rel) => fs.readFileSync(path.join(WEB, 'js', rel), 'utf-8');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf-8');

const POOL_IDS = ['poolStatusBadge', 'poolRefreshBtn', 'poolConnectBtn', 'poolClearBtn',
  'poolTotal', 'poolSteady', 'poolBusy', 'poolCooling', 'poolFree', 'poolTableBody'];

function inside(node, ancestor) {
  for (let n = node; n; n = n.parent) if (n === ancestor) return true;
  return false;
}

/* The panels index.html declares (element id ↔ data-window id). */
function panelsFromHtml() {
  const panels = [...html.matchAll(/<div class="panel[^"]*" id="(win\w+)" data-window="(\w+)">/g)]
    .map((m) => ({ elId: m[1], winId: m[2] }));
  return { panels };
}

describe('live_debug window (S8 — mount + L-5 rescue)', () => {
  test('index.html registers winLiveDebug and the page_pool orphan is gone', () => {
    const { panels } = panelsFromHtml();
    const ids = panels.map((p) => p.winId);
    assert.ok(ids.includes('live_debug'), 'winLiveDebug/data-window="live_debug" present');
    assert.ok(!ids.includes('page_pool'), 'no unregistered data-window="page_pool" panel');
    const live = panels.find((p) => p.winId === 'live_debug');
    assert.equal(live.elId, 'winLiveDebug');
    // the pool markup is INSIDE the rescued window (same inner ids, so the frozen PagePoolPanel still binds)
    const start = html.indexOf('id="winLiveDebug"');
    const end = html.indexOf('<div class="panel', start + 1);
    const block = html.slice(start, end > 0 ? end : undefined);
    for (const id of POOL_IDS) assert.ok(block.includes(`id="${id}"`), `${id} inside winLiveDebug`);
    assert.match(block, /Live Worker &amp; Queue Debug|Live Worker & Queue Debug/);
  });

  test('the grid mounts winLiveDebug and does not destroy it on render()', () => {
    assert.ok(ALL_WINDOW_IDS.includes('live_debug'), 'harness registry has the 16th window');
    const h = createSashGrid();
    const find = (n, id) => { if (n.id === id) return n; for (const c of n.children) { const r = find(c, id); if (r) return r; } return null; };
    h.SashGrid.render();
    const win = find(h.body, 'winLiveDebug');
    assert.ok(win, 'winLiveDebug exists after render');
    assert.ok(inside(win, h.gridEl), 'winLiveDebug is inside #sashGrid (not discarded by replaceChildren)');
    for (const id of ALL_WINDOW_IDS) assert.ok(inside(find(h.body, panelIdOf(id)), h.gridEl), id);
  });

  test('the pool panel still finds its ids after the rescue (frozen panel untouched)', () => {
    const byId = {};
    for (const id of POOL_IDS) byId[id] = new El(id.endsWith('Btn') ? 'button' : 'div');
    const sandbox = { console, JSON, Object, Array, Math, Date, setTimeout: () => 1, setInterval: () => 1,
      document: { getElementById: (id) => byId[id] || null } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const f of ['panels/page-pool/store.js', 'panels/page-pool/render.js', 'panels/page-pool/actions.js', 'panels/page-pool.js']) {
      vm.runInContext(readJs(f), sandbox, { filename: f });
    }
    vm.runInContext('PagePoolPanel.init()', sandbox);
    const bound = ['poolRefreshBtn', 'poolClearBtn', 'poolConnectBtn'].map((id) => (byId[id]._listeners.click || []).length);
    assert.deepEqual(bound, [1, 1, 1]);
  });

  test('_PANEL_INITS includes LiveDebugPanel and the module publishes itself on window', () => {
    const inits = readJs('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1];
    assert.match(inits, /'LiveDebugPanel'/);
    assert.ok(html.includes('js/panels/live-debug.js'), 'index.html loads the module');
    const warnings = [];
    const sandbox = { console: { warn: (...a) => warnings.push(a.join(' ')), log() {}, error() {} }, JSON, Object, Array, Set, WeakMap, Map, Number, String, Math, Date,
      setInterval: () => 1, document: { getElementById: () => null, readyState: 'complete', addEventListener() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const f of ['core/boot.js', 'panels/live-debug/store.js', 'panels/live-debug/render.js', 'panels/live-debug/actions.js', 'panels/live-debug.js']) {
      assert.ok(html.includes(`js/${f}`), `index.html loads ${f}`);
      vm.runInContext(readJs(f), sandbox, { filename: f });
    }
    const panel = vm.runInContext("Boot.panel('LiveDebugPanel')", sandbox);
    assert.ok(panel && typeof panel.init === 'function');
    assert.deepEqual(warnings, []);
    vm.runInContext("LiveDebugPanel.init()", sandbox);  // no DOM, no bridge: must not throw
  });

  test('the three JS registries and Python agree on 18 windows, order and titles', () => {
    const constants = readJs('sash-core/constants.js');
    const jsWindows = [...constants.matchAll(/\{\s*id:\s*'([^']+)',\s*title:\s*'([^']+)'\s*\}/g)].map((m) => [m[1], m[2]]);
    assert.equal(jsWindows.length, 18);
    assert.match(constants, /VERSION:\s*8\b/);
    const py = JSON.parse(execFileSync(path.resolve(__dirname, '../../.venv/bin/python'), ['-c',
      'import json; from app.core.window_catalog import WINDOWS; print(json.dumps([[w["id"], w["title"]] for w in WINDOWS]))'],
      { cwd: path.resolve(__dirname, '../..'), encoding: 'utf-8' }));
    assert.deepEqual(jsWindows, py);
    const store = readJs('sash-grid-windows/store.js');
    for (const [id] of jsWindows) assert.match(store, new RegExp(`\\b${id}:\\s*'${panelIdOf(id)}'`), `store.js ${id}`);
    assert.doesNotMatch(readJs('sash-grid.js'), /WIN_ICONS/, 'L-8: the dead icon table is gone');
  });

  test('frozen JS files did not grow (same-line appends only)', () => {
    const metrics = JSON.parse(execFileSync('node', [path.resolve(__dirname, '../../tools/js_metrics.js'), path.join(WEB, 'js'), '--json'], { encoding: 'utf-8' }));
    const file = (rel) => metrics.find((e) => e.isFile && e.file.endsWith(rel)).fileLines;
    const maxFunc = (rel) => Math.max(...metrics.filter((e) => !e.isFile && e.file && e.file.endsWith(rel)).map((e) => e.loc || 0));
    assert.ok(file('sash-core/constants.js') <= 25 && maxFunc('sash-core/constants.js') <= 22, 'constants.js 25 / 22');
    assert.ok(file('sash-grid-windows/store.js') <= 122 && maxFunc('sash-grid-windows/store.js') <= 14, 'store.js 122 / 14');
    assert.ok(file('arena-app.js') <= 176, 'arena-app.js 176');
    assert.ok(file('sash-grid.js') <= 114, 'sash-grid.js 123 → ≤114 (WIN_ICONS deleted)');
  });
});

/* ── part 2 (S9): the content ─────────────────────────────────────────────── */
const LIVE_IDS = ['liveQueueHead', 'liveWorkers', 'liveReceivers', 'liveCadence', 'liveRefreshBtn'];

const T0 = 1_000_000_000;  // "now" in seconds; Date.now() is ms

function bootLivePanel({ now = T0 * 1000 } = {}) {
  const byId = {};
  for (const id of LIVE_IDS) byId[id] = new El(id.endsWith('Btn') ? 'button' : 'div');
  const calls = [];
  const listeners = {};
  const bridge = new Proxy({}, { get(_t, k) {
    if (typeof k !== 'string') return undefined;
    const fn = (...a) => { calls.push(k); const cb = a.find((x) => typeof x === 'function'); if (cb) cb('{}'); };
    fn.connect = (h) => { (listeners[k] ||= []).push(h); };
    return fn;
  } });
  const clock = { now };
  const timers = [];
  const sandbox = {
    console, JSON, Object, Array, Math, Number, String, Set, Map, WeakMap, parseInt, parseFloat, isNaN,
    Date: { now: () => clock.now },
    setTimeout: () => 1, clearTimeout() {}, setInterval: (f) => { timers.push(f); return 1; }, clearInterval() {},
    document: { getElementById: (id) => byId[id] || null, readyState: 'complete', addEventListener() {} },
    App: { bridge },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const f of ['core/boot.js', 'panels/live-debug/store.js', 'panels/live-debug/render.js', 'panels/live-debug/actions.js', 'panels/live-debug.js']) {
    vm.runInContext(readJs(f), sandbox, { filename: f });
  }
  vm.runInContext('LiveDebugPanel.init()', sandbox);
  const push = (signal, payload) => { for (const h of listeners[signal] || []) h(typeof payload === 'string' ? payload : JSON.stringify(payload)); };
  const tick = () => { for (const f of timers) f(); };
  const raw = (id) => byId[id].innerHTML || byId[id].textContent || '';
  return { byId, calls, listeners, clock, push, tick, sandbox, raw, text: (id) => raw(id).replace(/<[^>]+>/g, '') };
}

const LIVE = { queued: 3, next_image: 'a.png', receivers: { total: 4, receivers: 2, not_receivers: 2 }, run_state: 'live',
  url_interval_ms: 5000, last_pass_at: T0 - 2, passes: 12, captcha_cap_sec: 300 };
const page = (tab_id, extra = {}) => ({ tab_id, title: 'T ' + tab_id, url: 'https://arena.ai/' + tab_id, status: 'steady', is_connected: true,
  current_job_id: '', current_image: '', busy_since: 0, cooldown_remaining: 0, cooldown_reason: '', jobs_completed: 1, captcha_count: 0, rate_limit_count: 0, ...extra });
const POOL3 = { total: 3, steady: 2, busy: 1, cooling: 0, free: 2, pages: [page('t1'), page('t2', { status: 'busy', current_image: 'b.png', current_job_id: 'J-2', busy_since: T0 - 30 }), page('t3')] };

describe('live_debug window (S9 — content from pushed payloads only)', () => {
  test('queue head renders count and first image name', () => {
    const h = bootLivePanel();
    h.push('progress_updated', { live: LIVE });
    assert.match(h.text('liveQueueHead'), /3 pending · first: a\.png/);
    h.push('progress_updated', { live: { ...LIVE, queued: 0, next_image: '' } });
    assert.match(h.text('liveQueueHead'), /0 pending · queue empty/);
    assert.match(h.text('liveReceivers'), /2 of 4 rows can receive/);
  });

  test('a waiting-captcha worker renders the paused-timeout line (never silent)', () => {
    const h = bootLivePanel();
    h.push('progress_updated', { live: LIVE });
    h.push('page_pool_updated', { ...POOL3, pages: [page('t1', { status: 'waiting_captcha', current_image: 'c.png', busy_since: T0 - 90 })] });
    const html = h.text('liveWorkers');
    assert.match(html, /waiting_captcha/);
    assert.match(html, /timeout paused 01:30/);
    assert.match(html, /cap 05:00/);
  });

  test('new and removed webpages appear and disappear with no bridge call', () => {
    const h = bootLivePanel();
    h.push('page_pool_updated', POOL3);
    assert.equal((h.raw('liveWorkers').match(/class="live-worker /g) || []).length, 3);
    h.push('page_pool_updated', { ...POOL3, total: 2, pages: [page('t1'), page('t3')] });
    const rows = h.raw('liveWorkers');
    assert.equal((rows.match(/class="live-worker /g) || []).length, 2);
    assert.doesNotMatch(rows, /t2/);
    assert.deepEqual(h.calls, []);
    h.push('page_pool_updated', { ...POOL3, total: 0, pages: [] });
    assert.match(h.text('liveWorkers'), /no worker tabs/);
  });

  test('the ticker recomputes elapsed without a bridge call', () => {
    const h = bootLivePanel();
    h.push('progress_updated', { live: LIVE });
    h.push('page_pool_updated', POOL3);
    const before = h.text('liveWorkers');
    assert.match(before, /b\.png · 00:30/);
    h.clock.now += 5000;
    h.tick();
    assert.match(h.text('liveWorkers'), /b\.png · 00:35/);
    assert.match(h.text('liveCadence'), /last pass 7 s ago/);
    assert.deepEqual(h.calls, []);
  });

  test('cadence is read-only text (D-12R: the URL-list bar is the only writer)', () => {
    const h = bootLivePanel();
    h.push('progress_updated', { live: LIVE });
    assert.match(h.text('liveCadence'), /reconcile every 5\.0 s · last pass 2 s ago · 12 passes · run live/);
    const block = html.slice(html.indexOf('id="winLiveDebug"'), html.indexOf('<div class="panel', html.indexOf('id="winLiveDebug"') + 1));
    assert.doesNotMatch(block, /<input/);
    for (const f of ['panels/live-debug.js', 'panels/live-debug/store.js', 'panels/live-debug/render.js', 'panels/live-debug/actions.js']) {
      assert.doesNotMatch(readJs(f), /save_settings|set_url_interval|reconcile_interval/, f);
    }
  });

  test('the panel publishes itself, self-connects, and listeners.js is untouched', () => {
    const h = bootLivePanel();
    assert.ok(vm.runInContext('window.LiveDebugPanel === LiveDebugPanel', h.sandbox));
    assert.equal((h.listeners.progress_updated || []).length, 1);
    assert.equal((h.listeners.page_pool_updated || []).length, 1);
    vm.runInContext('LiveDebugPanel.init()', h.sandbox);  // idempotent: a second init binds nothing twice
    assert.equal((h.listeners.progress_updated || []).length, 1);
    assert.equal((h.byId.liveRefreshBtn._listeners.click || []).length, 1);
    h.byId.liveRefreshBtn._listeners.click[0]();
    assert.deepEqual(h.calls, ['get_page_pool_status']);  // the ONE read; no writes
    assert.doesNotMatch(readJs('arena-app/listeners.js'), /LiveDebug/);
    assert.equal(readJs('arena-app/listeners.js').split('\n').length, 194, 'listeners.js frozen at 193 lines');
  });
});

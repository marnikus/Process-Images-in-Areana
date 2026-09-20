/**
 * Live Worker & Queue Debug — the 16th window (S8: registration + the L-5 rescue;
 * S9 appends the content tests). Real sash grid in the fake DOM; real index.html.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { createSashGrid, ALL_WINDOW_IDS } from './sash_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

describe('winLiveDebug registration (S8)', () => {
  test('the grid mounts winLiveDebug and an unregistered panel is the one that gets dropped', () => {
    assert.ok(ALL_WINDOW_IDS.includes('live_debug'));
    const h = createSashGrid();
    const win = h.gridEl.querySelector('.sash-window[data-win="live_debug"]');
    assert.ok(win, 'registered window must live inside #sashGrid after init/render');
    assert.equal(win.querySelector(':scope > .panel').id, 'winLiveDebug');
    // the L-5 mechanism: a panel with an id no registry knows is not mounted anywhere
    const orphan = new El('div'); orphan.id = 'winPagePool'; orphan.dataset.window = 'page_pool';
    h.body.appendChild(orphan);
    h.SashGrid.render();
    assert.equal(h.gridEl.querySelector('.sash-window[data-win="page_pool"]'), null);
    assert.equal(h.gridEl.querySelectorAll('.sash-window').length, ALL_WINDOW_IDS.length);
  });

  test('the pool panel still finds its ids inside the rescued window', () => {
    const start = html.indexOf('id="winLiveDebug"');
    const end = html.indexOf('<!-- ACTIVITY LOG -->', start);
    const block = html.slice(start, end);
    for (const id of ['poolStatusBadge', 'poolRefreshBtn', 'poolConnectBtn', 'poolClearBtn', 'poolTableBody', 'poolTotal', 'poolFree']) {
      assert.ok(block.includes(`id="${id}"`), id);
    }
    assert.ok(!html.includes('data-window="page_pool"'));
    assert.ok(block.includes('Live Worker &amp; Queue Debug') || block.includes('Live Worker & Queue Debug'));
  });

  test('_PANEL_INITS includes LiveDebugPanel and the module publishes itself', () => {
    const app = fs.readFileSync(path.join(WEB, 'js/arena-app.js'), 'utf8');
    const block = app.split('_PANEL_INITS = [')[1].split('];')[0];
    assert.ok(block.includes("'LiveDebugPanel'"));
    const panel = fs.readFileSync(path.join(WEB, 'js/panels/live-debug.js'), 'utf8');
    assert.ok(/window\.LiveDebugPanel\s*=\s*LiveDebugPanel/.test(panel));
    assert.ok(html.includes('js/panels/live-debug.js'));
  });
});

/* ── part 2 (S9): the window's content ─────────────────────────────────────── */
import vm from 'node:vm';

function loadPanel({ now = () => 1_000_000_000, bridge = null } = {}) {
  const els = {};
  const mk = (id) => { const el = new El('div'); el.id = id; el.innerHTML = ''; el.textContent = ''; els[id] = el; return el; };
  ['liveDebugRoot', 'ldQueueHead', 'ldWorkers', 'ldCadence', 'ldRefreshBtn'].forEach(mk);
  els.ldRefreshBtn.listeners = {};
  els.ldRefreshBtn.addEventListener = (ev, fn) => { (els.ldRefreshBtn.listeners[ev] ||= []).push(fn); };
  const calls = [];
  const proxy = bridge && new Proxy(bridge, { get(t, p) { const v = t[p]; if (typeof v === 'function') return (...a) => { calls.push([p, ...a]); return v.apply(t, a); }; return v; } });
  const timers = [];
  const sandbox = {
    console, JSON, Math, Object, Array, Map, Set, Error, Number, String, Date, parseInt, isNaN, WeakMap,
    setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearInterval: () => {},
    document: { getElementById: (id) => els[id] || null, readyState: 'complete', addEventListener() {}, hidden: false },
    App: { bridge: proxy }, LogConsole: { log: () => {} },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;
  vm.createContext(sandbox);
  const run = (rel) => vm.runInContext(fs.readFileSync(path.join(WEB, 'js', rel), 'utf8'), sandbox, { filename: rel });
  run('core/boot.js');
  run('panels/live-debug/store.js'); run('panels/live-debug/render.js'); run('panels/live-debug/actions.js'); run('panels/live-debug.js');
  sandbox.LiveDebugStore.now = now;
  return { sandbox, els, calls, timers, panel: sandbox.LiveDebugPanel, store: sandbox.LiveDebugStore };
}

const text = (el) => (el.innerHTML || el.textContent || '');

describe('Live Worker & Queue Debug content (S9)', () => {
  test('queue head renders count and first image name', () => {
    const { panel, els } = loadPanel();
    panel.init();
    panel.onLive({ queued: 3, next_image: 'a.png', receivers: { total: 2, receivers: 1, not_receivers: 1 }, run_state: 'running', wait_reason: '' });
    assert.match(text(els.ldQueueHead), /3 pending/);
    assert.match(text(els.ldQueueHead), /first: a\.png/);
    assert.match(text(els.ldQueueHead), /1 of 2 rows can receive/);
  });

  test('a waiting-captcha worker renders the paused-timeout line', () => {
    const t0 = 1_000_000_000;
    const { panel, els } = loadPanel({ now: () => t0 });
    panel.init();
    panel.onPool({ total: 1, pages: [{ tab_id: 'tab12345678', title: 'Arena', status: 'waiting_captcha', is_connected: true, current_image: 'x.png', busy_since: t0 / 1000 - 90, cooldown_remaining: 0, jobs_completed: 2 }] });
    const line = text(els.ldWorkers);
    assert.match(line, /tab12345678|tab12345/);
    assert.match(line, /captcha/i);
    assert.match(line, /timeout paused/);
    assert.match(line, /1:30|90 s/);
  });

  test('new and removed webpages appear and disappear with no bridge call', () => {
    const bridge = { get_page_pool_status: (cb) => cb(JSON.stringify({ pages: [] })) };
    const { panel, els, calls } = loadPanel({ bridge });
    panel.init();
    const afterBoot = calls.length;                     // init reads the pool once (the push only arrives on change)
    const page = (id) => ({ tab_id: id, title: id, status: 'steady', is_connected: true, current_image: '', busy_since: null, cooldown_remaining: 0, jobs_completed: 0 });
    panel.onPool({ total: 3, pages: [page('t1'), page('t2'), page('t3')] });
    assert.equal((text(els.ldWorkers).match(/class="ld-worker"/g) || []).length, 3);
    panel.onPool({ total: 2, pages: [page('t1'), page('t3')] });
    const html = text(els.ldWorkers);
    assert.equal((html.match(/class="ld-worker"/g) || []).length, 2);
    assert.ok(!html.includes('>t2<'));
    assert.equal(calls.length, afterBoot);              // pushes are rendered without asking the bridge
  });

  test('the ticker recomputes elapsed without a bridge call', () => {
    let t = 1_000_000_000;
    const bridge = { get_page_pool_status: (cb) => cb('{}') };
    const { panel, els, calls, timers, store } = loadPanel({ now: () => t, bridge });
    panel.init();
    const afterBoot = calls.length;
    panel.onPool({ total: 1, pages: [{ tab_id: 't1', title: 'A', status: 'busy', is_connected: true, current_image: 'img.png', busy_since: t / 1000 - 10, cooldown_remaining: 0, jobs_completed: 0 }] });
    const before = text(els.ldWorkers);
    t += 5000;
    assert.ok(timers.length >= 1);
    store.tick();
    assert.notEqual(text(els.ldWorkers), before);
    assert.match(text(els.ldWorkers), /15 s/);
    assert.equal(calls.length, afterBoot);              // the ticker never asks the bridge
  });

  test('cadence is read-only text (no input, no save_settings)', () => {
    const t = 1_000_000_000;
    const { panel, els, calls } = loadPanel({ now: () => t, bridge: { save_settings: () => {} } });
    panel.init();
    panel.onLive({ queued: 0, next_image: '', receivers: { total: 0, receivers: 0, not_receivers: 0 }, run_state: 'idle', wait_reason: 'no_work', url_interval_ms: 5000, last_pass_at: t / 1000 - 2, passes: 4 });
    const html = text(els.ldCadence);
    assert.match(html, /reconcile every 5\.0 s/);
    assert.match(html, /last pass 2 s ago/);
    assert.ok(!html.includes('<input'));
    assert.deepEqual(calls.filter(([n]) => n === 'save_settings'), []);
  });

  test('the panel publishes itself, self-connects, and refresh reads the pool once', () => {
    const connected = [];
    const bridge = {
      progress_updated: { connect: (fn) => connected.push('progress_updated') },
      page_pool_updated: { connect: (fn) => connected.push('page_pool_updated') },
      get_page_pool_status: (cb) => cb(JSON.stringify({ total: 1, pages: [{ tab_id: 'z1', title: 'Z', status: 'steady', is_connected: true, current_image: '', jobs_completed: 0 }] })),
    };
    const { sandbox, panel, els, calls } = loadPanel({ bridge });
    assert.equal(typeof sandbox.window.LiveDebugPanel, 'object');
    panel.init();
    assert.deepEqual(connected.sort(), ['page_pool_updated', 'progress_updated']);
    const reads = () => calls.filter(([n]) => n === 'get_page_pool_status').length;
    assert.equal(reads(), 1);                           // one initial read at connect
    panel.refresh();
    assert.equal(reads(), 2);                           // Refresh = exactly one more read, no writes
    assert.deepEqual(calls.filter(([n]) => n !== 'get_page_pool_status' && !/_updated$/.test(n)), []);
    assert.match(text(els.ldWorkers), /z1/);
    const listeners = fs.readFileSync(path.join(WEB, 'js/arena-app/listeners.js'), 'utf8');
    assert.equal(listeners.split('\n').length, 194);   // frozen: new panels self-connect
  });
});

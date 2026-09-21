/**
 * The 17th window `job_history` — part 1: the mount (same contract as S8).
 *
 * `winJobHistory` is registered in every registry (Python catalog,
 * `constants.js`, `store.js` winElIds, `_PANEL_INITS`) and mounts inside the
 * grid — never an L-5 orphan. Part 2: the content — one row per finished job
 * (newest first) from the pushed `job_history_updated` payload plus the
 * `get_job_history` reply, with the display-limit control owning both its
 * views (the url-list/interval.js pattern).
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';
import { createSashGrid, ALL_WINDOW_IDS, panelIdOf } from './sash_harness.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.resolve(__dirname, '../../app/ui/web');
const readJs = (rel) => fs.readFileSync(path.join(WEB, 'js', rel), 'utf-8');
const html = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');

const HISTORY_FILES = ['panels/job-history/store.js', 'panels/job-history/render.js',
  'panels/job-history/actions.js', 'panels/job-history/limit.js', 'panels/job-history.js'];

function inside(node, ancestor) {
  for (let n = node; n; n = n.parent) if (n === ancestor) return true;
  return false;
}

describe('job_history window (mount)', () => {
  test('index.html registers winJobHistory with the pool-style table and limit control', () => {
    assert.ok(html.includes('id="winJobHistory" data-window="job_history"'), 'panel present');
    assert.ok(html.includes('css/job-history.css'), 'stylesheet loaded');
    for (const f of HISTORY_FILES) assert.ok(html.includes(`js/${f}`), `index.html loads ${f}`);
    const start = html.indexOf('id="winJobHistory"');
    const end = html.indexOf('<div class="panel', start + 1);
    const block = html.slice(start, end > 0 ? end : undefined);
    for (const id of ['historyTableBody', 'historyCount', 'historyRefreshBtn', 'historyClearBtn', 'historyLimit', 'historyLimitSaveBtn']) {
      assert.ok(block.includes(`id="${id}"`), `${id} inside winJobHistory`);
    }
    for (const col of ['Tab ID', 'Tab #', 'Job #', 'Status', 'Error log', 'Image', 'Folder', 'Link', 'Time start', 'Time finished', 'Captcha']) {
      assert.ok(block.includes(`<th>${col}</th>`), `column ${col}`);
    }
    assert.ok(html.includes('id="setHistoryLimit"'), 'Settings mirrors the limit control');
  });

  test('the grid mounts winJobHistory and does not destroy it on render()', () => {
    assert.ok(ALL_WINDOW_IDS.includes('job_history'), 'harness registry has the 17th window');
    assert.equal(panelIdOf('job_history'), 'winJobHistory');
    const h = createSashGrid();
    const find = (n, id) => { if (n.id === id) return n; for (const c of n.children) { const r = find(c, id); if (r) return r; } return null; };
    h.SashGrid.render();
    const win = find(h.body, 'winJobHistory');
    assert.ok(win, 'winJobHistory exists after render');
    assert.ok(inside(win, h.gridEl), 'winJobHistory is inside #sashGrid (not discarded by replaceChildren)');
  });

  test('_PANEL_INITS includes both history modules and they publish themselves on window', () => {
    const inits = readJs('arena-app.js').match(/_PANEL_INITS\s*=\s*\[([\s\S]*?)\]/)[1];
    assert.match(inits, /'JobHistoryPanel'/);
    assert.match(inits, /'JobHistoryLimit'/);
    const sandbox = { console: { warn() {}, log() {}, error() {} }, JSON, Object, Array, Set, WeakMap, Map, Number, String, Math, Date, parseInt, isNaN,
      setInterval: () => 1, setTimeout: () => 1, document: { getElementById: () => null, readyState: 'complete', addEventListener() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
    for (const f of HISTORY_FILES) vm.runInContext(readJs(f), sandbox, { filename: f });
    for (const name of ['JobHistoryPanel', 'JobHistoryLimit', 'JobHistoryStore', 'JobHistoryRender', 'JobHistoryActions']) {
      const obj = vm.runInContext(`Boot.panel('${name}')`, sandbox);
      assert.ok(obj, `${name} published on window`);
    }
    vm.runInContext('JobHistoryPanel.init()', sandbox); // no DOM, no bridge: must not throw
    vm.runInContext('JobHistoryLimit.init()', sandbox);
  });
});

/* ── part 2: the content ─────────────────────────────────────────────────── */
const HISTORY_IDS = ['historyTableBody', 'historyCount', 'historyRefreshBtn', 'historyClearBtn',
  'historyLimit', 'historyLimitSaveBtn', 'setHistoryLimit', 'settingsSaveBtn'];

function bootHistoryPanel() {
  const byId = {};
  for (const id of HISTORY_IDS) byId[id] = new El(id.endsWith('Btn') ? 'button' : (id === 'historyTableBody' ? 'tbody' : 'div'));
  const calls = [];
  const listeners = {};
  const bridge = new Proxy({}, { get(_t, k) {
    if (typeof k !== 'string') return undefined;
    const fn = (...a) => { calls.push(k); const cb = a.find((x) => typeof x === 'function'); if (cb) cb('{}'); };
    fn.connect = (h) => { (listeners[k] ||= []).push(h); };
    return fn;
  } });
  const sandbox = {
    console, JSON, Object, Array, Math, Number, String, Set, Map, WeakMap, parseInt, parseFloat, isNaN,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
    document: { getElementById: (id) => byId[id] || null, querySelector: () => null, querySelectorAll: () => [],
      readyState: 'complete', addEventListener() {}, createElement: (t) => new El(t) },
    App: { bridge },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
  for (const f of HISTORY_FILES) vm.runInContext(readJs(f), sandbox, { filename: f });
  vm.runInContext('JobHistoryPanel.init()', sandbox);
  vm.runInContext('JobHistoryLimit.init()', sandbox);
  const push = (signal, payload) => { for (const h of listeners[signal] || []) h(typeof payload === 'string' ? payload : JSON.stringify(payload)); };
  const raw = (id) => byId[id].innerHTML || byId[id].textContent || '';
  return { byId, calls, listeners, push, sandbox, raw, text: (id) => raw(id).replace(/<[^>]+>/g, '') };
}

const row = (over = {}) => ({ job_no: 7, job_id: 'c1', tab_id: 'tab-abcdef123456', worker_no: 2,
  status: 'completed', error: '', image_id: 'i-a', image: 'a.png', image_path: '/in/a.png',
  folder: '/in', output_path: '/in/a_AI.png', started: '2026-09-21T10:00:01+00:00',
  finished: '2026-09-21T10:00:41+00:00', captcha: 0, ...over });
const PAYLOAD = { entries: [row(), row({ job_no: 6, job_id: 'c0', status: 'failed', error: 'Attach failed: no file input',
  output_path: '', folder: '', captcha: 2, started: '2026-09-21T09:59:01+00:00', finished: '2026-09-21T09:59:20+00:00' })],
  limit: 50, total: 2, next_job_no: 8 };

describe('job_history window (content)', () => {
  test('the first paint pulls get_job_history and renders one row per job, newest first', () => {
    const h = bootHistoryPanel();
    assert.ok(h.calls.includes('get_job_history'), 'initial pull on bridge-ready');
    h.push('job_history_updated', PAYLOAD);
    const body = h.raw('historyTableBody');
    assert.equal((body.match(/<tr>/g) || []).length, 2);
    assert.ok(body.indexOf('>7<') < body.indexOf('>6<'), 'newest first');
    assert.match(h.text('historyTableBody'), /✓ completed/);
    assert.match(h.text('historyTableBody'), /✗ failed/);
    assert.match(h.text('historyCount'), /2 shown · 2 stored/);
  });

  test('every column renders: tab, numbers, error, image, folder, link, times, captcha', () => {
    const h = bootHistoryPanel();
    h.push('job_history_updated', PAYLOAD);
    const t = h.text('historyTableBody');
    const body = h.raw('historyTableBody');
    assert.match(t, /tab-abc/); // tab id truncated, full id in the title
    assert.ok(body.includes('title="tab-abcdef123456"'), 'full tab id in title');
    assert.match(t, /#2/);
    assert.match(t, /Attach failed: no file input/);
    assert.match(t, /a\.png/);
    assert.ok(body.includes('data-img-id="i-a"'), 'thumb hook carries the image id');
    assert.match(t, /\/in/);
    assert.ok(body.includes('a_AI.png'), 'output link names the finished file');
    assert.ok(body.includes('data-act="reveal"'), 'folder reveal button');
    assert.ok(body.includes('data-act="copy"'), 'link copy button');
    assert.match(t, /10:00:01/);
    assert.match(t, /10:00:41/);
    assert.match(t, /🛡 ×2/);
  });

  test('failed rows show no destination and zero-captcha rows stay quiet', () => {
    const h = bootHistoryPanel();
    h.push('job_history_updated', { entries: [row({ status: 'failed', error: 'x', output_path: '', folder: '' })], limit: 50, total: 1, next_job_no: 2 });
    const body = h.raw('historyTableBody');
    assert.ok(!body.includes('file://'), 'no link without an output');
    assert.ok(!body.includes('data-act='), 'no path buttons without a destination');
    assert.ok(!body.includes('🛡'), 'no captcha badge at zero');
  });

  test('an empty log paints the empty state, garbage payloads never throw', () => {
    const h = bootHistoryPanel();
    h.push('job_history_updated', { entries: [], limit: 50, total: 0, next_job_no: 1 });
    assert.match(h.text('historyTableBody'), /no finished jobs yet/);
    h.push('job_history_updated', '{oops');
    h.push('job_history_updated', {});
    assert.match(h.text('historyTableBody'), /no finished jobs yet/);
  });

  test('the limit control owns both views and saves through save_settings', () => {
    const h = bootHistoryPanel();
    h.push('job_history_updated', { ...PAYLOAD, limit: 25 });
    assert.equal(h.byId.historyLimit.value, '25');
    assert.equal(h.byId.setHistoryLimit.value, '25');
    h.byId.historyLimit.value = '9999';
    vm.runInContext("JobHistoryLimit.save('historyLimit')", h.sandbox);
    assert.equal(h.byId.historyLimit.value, '500', 'clamped to the max');
    assert.ok(h.calls.includes('save_settings'), 'saved through the existing slot');
  });

  test('refresh pulls, clear clears, table buttons reveal and copy', () => {
    const h = bootHistoryPanel();
    h.push('job_history_updated', PAYLOAD);
    const before = h.calls.filter((c) => c === 'get_job_history').length;
    vm.runInContext('JobHistoryPanel.refresh()', h.sandbox);
    assert.equal(h.calls.filter((c) => c === 'get_job_history').length, before + 1);
    vm.runInContext('JobHistoryPanel.clear()', h.sandbox);
    assert.ok(h.calls.includes('clear_job_history'));
    vm.runInContext("JobHistoryActions.onTableClick({target:{closest:()=>({dataset:{act:'reveal',path:'/in'}})}})", h.sandbox);
    assert.ok(h.calls.includes('reveal_in_explorer'));
    vm.runInContext("JobHistoryActions.onTableClick({target:{closest:()=>({dataset:{act:'copy',path:'/in/a_AI.png'}})}})", h.sandbox);
    assert.ok(h.calls.includes('copy_path_to_clipboard'));
    vm.runInContext('JobHistoryActions.onTableClick({target:{closest:()=>null}})', h.sandbox); // no button: silent
  });

  test('clear asks for confirmation when a confirm dialog exists', () => {
    const h = bootHistoryPanel();
    h.sandbox.confirm = () => false;
    assert.equal(vm.runInContext('JobHistoryPanel.clear()', h.sandbox), false);
    assert.ok(!h.calls.includes('clear_job_history'));
    h.sandbox.confirm = () => true;
    vm.runInContext('JobHistoryPanel.clear()', h.sandbox);
    assert.ok(h.calls.includes('clear_job_history'));
  });

  test('async thumbs land in the history cache (own selector, queue untouched)', () => {
    const h = bootHistoryPanel();
    h.push('job_history_updated', PAYLOAD);
    const handlers = h.listeners['thumbnail_ready'] || [];
    assert.ok(handlers.length > 0, 'facade self-connects thumbnail_ready');
    for (const fn of handlers) fn('i-a', JSON.stringify({ ok: true, data_url: 'data:image/png;base64,ZZZ' }));
    const cached = vm.runInContext("JobHistoryStore.thumbCache['i-a']", h.sandbox);
    assert.equal(cached, 'data:image/png;base64,ZZZ');
  });
});

/* ── part 3: readable tab handles (D-7, merged with the alias feature) ────── */
describe('job_history tab column (readable ids)', () => {
  const render = () => {
    const sandbox = { console, JSON, Object, Array, Math, Number, String, parseInt, isNaN };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'core/boot.js' });
    vm.runInContext(readJs('core/tab-label.js'), sandbox, { filename: 'core/tab-label.js' });
    vm.runInContext(readJs('panels/job-history/store.js'), sandbox, { filename: 'store.js' });
    vm.runInContext(readJs('panels/job-history/render.js'), sandbox, { filename: 'render.js' });
    return sandbox;
  };

  test('the frozen row label wins — a finished job keeps the name it ran under', () => {
    const s = render();
    s.PagePoolPanel = { snapshot: { pages: [] } }; // tab already closed
    const cell = s.JobHistoryRender._tabCell(row({ tab_label: 'marnikus@gmail.com_3045' }));
    assert.match(cell, /marnikus@gmail\.com_3045/, 'readable handle shown');
    assert.ok(cell.includes("tab-abcdef123456"), "full hex still in the tooltip");
  });

  test('a legacy row with no stored label falls back to the live pool lookup', () => {
    const s = render();
    s.PagePoolPanel = { snapshot: { pages: [{ tab_id: 'tab-abcdef123456', tab_label: 'live@x.com_0007' }] } };
    assert.match(s.JobHistoryRender._tabCell(row()), /live@x\.com_0007/);
  });

  test('no label anywhere degrades to the short id, never an empty cell', () => {
    const s = render();
    s.PagePoolPanel = { snapshot: { pages: [] } };
    const cell = s.JobHistoryRender._tabCell(row());
    assert.match(cell, />tab-abcd</, 'short id fallback');
  });

  test('history and the worker table agree on the same tab', () => {
    const s = render();
    s.PagePoolPanel = { snapshot: { pages: [{ tab_id: 'tab-abcdef123456', tab_label: 'a@b.com_0042' }] } };
    const poolLabel = s.TabLabel.of('tab-abcdef123456');
    assert.ok(s.JobHistoryRender._tabCell(row()).includes(poolLabel), 'one handle, both views');
  });
});

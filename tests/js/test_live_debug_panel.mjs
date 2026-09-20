/**
 * The 16th window `live_debug` — part 1 (S8): the mount + the L-5 rescue.
 *
 * L-5: `index.html` declared `data-window="page_pool"`, an id no registry
 * knew; `SashGrid.render()` builds the grid from the registry and
 * `replaceChildren` discards everything else — the Page Pool markup was
 * destroyed by the first render. After S8 the markup lives inside the
 * registered `winLiveDebug` panel (inner ids untouched, the frozen
 * `PagePoolPanel` still binds), and the registry is one contract across
 * Python / `constants.js` / `store.js` / `_PANEL_INITS`. Part 2 (content)
 * lands in S9.
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
    const sandbox = { console: { warn: (...a) => warnings.push(a.join(' ')), log() {}, error() {} }, JSON, Object, Array, Set, WeakMap, Map,
      document: { getElementById: () => null, readyState: 'complete', addEventListener() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readJs('core/boot.js'), sandbox, { filename: 'boot.js' });
    vm.runInContext(readJs('panels/live-debug.js'), sandbox, { filename: 'live-debug.js' });
    const panel = vm.runInContext("Boot.panel('LiveDebugPanel')", sandbox);
    assert.ok(panel && typeof panel.init === 'function');
    assert.deepEqual(warnings, []);
    vm.runInContext("LiveDebugPanel.init()", sandbox);  // a stub in S8: must not throw
  });

  test('the three JS registries and Python agree on 16 windows, order and titles', () => {
    const constants = readJs('sash-core/constants.js');
    const jsWindows = [...constants.matchAll(/\{\s*id:\s*'([^']+)',\s*title:\s*'([^']+)'\s*\}/g)].map((m) => [m[1], m[2]]);
    assert.equal(jsWindows.length, 16);
    assert.match(constants, /VERSION:\s*6\b/);
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

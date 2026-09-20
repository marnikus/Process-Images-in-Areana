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
async function bootPage(t) {
  const dom = new JSDOM(fs.readFileSync(path.join(WEB, 'index.html'), 'utf8'), {
    runScripts: 'outside-only', url: 'https://arena.test/',
  });
  t.after(() => dom.window.close());
  const w = dom.window, calls = [], warnings = [], errors = [], slots = {};
  // Wait for jsdom's automatic event before installing the real boot handlers.
  await new Promise(resolve => w.document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  w.console = { log() {}, info() {}, debug() {}, warn: (...a) => warnings.push(a.join(' ')), error: (...a) => errors.push(a.join(' ')) };
  w.setTimeout = w.setInterval = w.requestAnimationFrame = () => 1;
  w.clearTimeout = w.clearInterval = () => {};
  const bridge = new Proxy({}, { get(_target, name) {
    if (!slots[name]) {
      slots[name] = (...args) => {
        calls.push({ name, args });
        args.find(a => typeof a === 'function')?.(JSON.stringify(name === 'get_action_blocks' ? [] : {}));
      };
      slots[name].connect = () => {};
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
  return { w, calls, warnings };
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

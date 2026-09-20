/**
 * folder-picker.js — Browse / Scan buttons through the REAL boot path.
 *
 * Regression (2026-10-03): every panel is a top-level `const`, which is a lexical
 * global and NOT `window.X`; Boot.bootPanels resolved panels via window[name], so
 * FolderPicker.init() never ran and the Browse button did nothing. This test
 * boots the real files in a V8 sandbox exactly like the page does.
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { El } from './fake_dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.resolve(__dirname, '../../app/ui/web/js');
const read = (f) => fs.readFileSync(path.join(JS, f), 'utf-8');

function makeBridge(replies = {}) {
  const calls = [];
  const bridge = {};
  for (const [slot, reply] of Object.entries(replies)) {
    bridge[slot] = (...args) => {
      const cb = typeof args[args.length - 1] === 'function' ? args.pop() : null;
      calls.push({ slot, args });
      if (cb) cb(typeof reply === 'function' ? reply(args) : JSON.stringify(reply));
    };
  }
  return { bridge, calls };
}

function load({ bridge = null } = {}) {
  const byId = {};
  for (const id of ['folderPickBtn', 'folderScanBtn', 'folderScanNewBtn', 'folderPathDisplay']) byId[id] = new El('button');
  byId.folderPathInput = new El('input');
  byId.folderPathInput.value = '';
  byId.folderPathDisplay.textContent = 'No folder selected';
  const logs = [];
  const warnings = [];
  const sandbox = {
    console: { warn: (...a) => warnings.push(a.join(' ')), error: (...a) => warnings.push('E:' + a.join(' ')), log() {} },
    JSON, Set, WeakMap, Map, Object, Array, String, Error, setTimeout,
    document: { readyState: 'complete', getElementById: (id) => byId[id] || null, addEventListener() {} },
    LogConsole: { log: (m, l) => logs.push([m, l]) },
    Dialog: { confirm: (_t, _m, _ok, onOk) => onOk() },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(read('core/boot.js'), sandbox, { filename: 'boot.js' });
  // arena-app.js declares `const App` and publishes it; mimic that contract here.
  vm.runInContext('const App = { bridge: null, state: null }; window.App = App;', sandbox, { filename: 'arena-app.js' });
  sandbox.App.bridge = bridge;
  vm.runInContext(read('panels/folder-picker.js'), sandbox, { filename: 'folder-picker.js' });
  return { sandbox, byId, logs, warnings };
}

describe('FolderPicker — global-name contract', () => {
  test('the module publishes itself: window.FolderPicker is the panel (const alone is invisible)', () => {
    const { sandbox } = load();
    assert.equal(typeof sandbox.window.FolderPicker, 'object');
    assert.equal(typeof sandbox.window.FolderPicker.init, 'function');
    // and the lexical const is the SAME object (no shadowing)
    assert.equal(vm.runInContext('FolderPicker === window.FolderPicker', sandbox), true);
  });

  test('Boot.bootPanels finds it by name and warns (never silent) for an unpublished panel', () => {
    const { sandbox, warnings } = load();
    sandbox.Boot.bootPanels(['FolderPicker', 'GhostPanel']);
    assert.ok(sandbox.Boot._booted.has('FolderPicker'));
    assert.ok(warnings.some((w) => w.includes('panel not found on window: GhostPanel')));
  });
});

describe('FolderPicker — Browse button', () => {
  test('click → bridge.pick_folder(startDir) → display + input updated on ok', () => {
    const { bridge, calls } = makeBridge({ pick_folder: { ok: true, path: 'C:/imgs' } });
    const { sandbox, byId, logs } = load({ bridge });
    sandbox.Boot.bootPanels(['FolderPicker']);
    byId.folderPathInput.value = '  D:/start  ';
    byId.folderPickBtn.dispatch('click', {});
    assert.deepEqual(calls, [{ slot: 'pick_folder', args: ['D:/start'] }]);
    assert.equal(byId.folderPathDisplay.textContent, 'C:/imgs');
    assert.equal(byId.folderPathInput.value, 'C:/imgs');
    assert.ok(logs.some(([m, l]) => l === 'success' && m.includes('C:/imgs')));
  });

  test('cancelled reply leaves the display alone; error reply is reported', () => {
    const { bridge } = makeBridge({ pick_folder: { ok: false, cancelled: true } });
    const { sandbox, byId, logs } = load({ bridge });
    sandbox.Boot.bootPanels(['FolderPicker']);
    byId.folderPickBtn.dispatch('click', {});
    assert.equal(byId.folderPathDisplay.textContent, 'No folder selected');
    assert.ok(logs.some(([m, l]) => l === 'info' && /cancelled/.test(m)));

    const bad = makeBridge({ pick_folder: { ok: false, error: 'No file dialog' } });
    const t2 = load({ bridge: bad.bridge });
    t2.sandbox.Boot.bootPanels(['FolderPicker']);
    t2.byId.folderPickBtn.dispatch('click', {});
    assert.ok(t2.logs.some(([m, l]) => l === 'error' && m.includes('No file dialog')));
  });

  test('booting twice binds ONE listener (bindOnce) — one pick per click', () => {
    const { bridge, calls } = makeBridge({ pick_folder: { ok: true, path: '/x' } });
    const { sandbox, byId } = load({ bridge });
    sandbox.Boot.bootPanels(['FolderPicker']);
    sandbox.Boot._reset();
    sandbox.Boot.bootPanels(['FolderPicker']);
    byId.folderPickBtn.dispatch('click', {});
    assert.equal(calls.length, 1);
  });

  test('missing slot is reported, never thrown or silent', () => {
    const { bridge } = makeBridge({});
    const { sandbox, byId, logs, warnings } = load({ bridge });
    sandbox.Boot.bootPanels(['FolderPicker']);
    assert.doesNotThrow(() => byId.folderPickBtn.dispatch('click', {}));
    assert.ok(warnings.some((w) => w.includes('bridge slot missing: pick_folder')));
    assert.ok(logs.some(([m, l]) => l === 'warn' && m.includes('pick_folder')));
  });
});

describe('FolderPicker — Scan buttons + Enter-to-set', () => {
  test('Scan calls scan_folder; New Batch confirms via Dialog then scan_folder_new_batch', () => {
    const { bridge, calls } = makeBridge({
      scan_folder: { ok: true, pending: true },
      scan_folder_new_batch: { ok: true, cleared: 3, pending: true },
    });
    const { sandbox, byId, logs } = load({ bridge });
    sandbox.Boot.bootPanels(['FolderPicker']);
    byId.folderScanBtn.dispatch('click', {});
    byId.folderScanNewBtn.dispatch('click', {});
    assert.deepEqual(calls.map((c) => c.slot), ['scan_folder', 'scan_folder_new_batch']);
    assert.ok(logs.some(([m]) => m.includes('cleared 3')));
  });

  test('Enter in the path box calls set_folder_path with the trimmed value', () => {
    const { bridge, calls } = makeBridge({ set_folder_path: { ok: true, path: '/data/imgs' } });
    const { sandbox, byId } = load({ bridge });
    sandbox.Boot.bootPanels(['FolderPicker']);
    byId.folderPathInput.value = ' /data/imgs ';
    byId.folderPathInput.dispatch('keydown', { key: 'Enter', target: byId.folderPathInput });
    assert.deepEqual(calls, [{ slot: 'set_folder_path', args: ['/data/imgs'] }]);
    assert.equal(byId.folderPathDisplay.textContent, '/data/imgs');
  });
});

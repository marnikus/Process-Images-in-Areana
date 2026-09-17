/**
 * Tier A — Logic tests for action-blocks.js stack presets + export (Node.js).
 * Save stores the full stack as a named preset rendered below as quick-load
 * chips; Export prefers the bridge folder-picker slot, Blob fallback stays.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const panelPath = path.resolve(__dirname, '../../app/ui/web/js/panels/action-blocks.js');
const panelCode = fs.readFileSync(panelPath, 'utf-8');

function fakeEl() {
  const el = {
    innerHTML: '', title: '', className: '', style: {}, dataset: {},
    children: [], listeners: {}, clicked: false,
    appendChild(c) { this.children.push(c); return c; },
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    querySelector() { return this._btn || (this._btn = fakeEl()); },
    click() { (this.listeners.click || []).forEach((fn) => fn({ target: { closest: () => null }, stopPropagation() {} })); },
  };
  return el;
}

function loadPanel({ bridge = null, confirmValue = true, promptValue = 'My stack' } = {}) {
  const logs = [];
  const byId = {};
  const fakeDocument = {
    getElementById: (id) => byId[id] || (byId[id] = fakeEl()),
    createElement: () => fakeEl(),
  };
  const calls = [];
  const fakeBridge = bridge ? new Proxy(bridge, {
    get(t, k) {
      if (k in t) return t[k];
      return (...args) => { calls.push([k, ...args]); };
    },
  }) : null;
  const sandbox = {
    console, JSON, Math, Object, Array, Map, Set, Error, URL, Date, Blob,
    document: fakeDocument,
    App: { bridge: fakeBridge },
    LogConsole: { log: (m, l) => logs.push([String(m), l || 'info']) },
    prompt: () => promptValue,
    confirm: () => confirmValue,
    alert: () => {},
  };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(panelCode + '\nthis.__P = ActionBlocksPanel;', sandbox, { filename: 'action-blocks.js' });
  return { panel: sandbox.__P, logs, calls, byId, fakeDocument };
}

const entry = (name, n = 2) => ({ name, blocks: Array.from({ length: n }, (_, i) => ({ block_id: `B${i}` })) });

describe('renderStackChips', () => {
  test('empty shows a placeholder hint', () => {
    const { panel, byId } = loadPanel();
    panel.stackPresets = [];
    panel.renderStackChips();
    assert.match(byId.stackPresetChips.innerHTML, /no saved stack presets/i);
  });

  test('chips show name and block count', () => {
    const { panel, byId } = loadPanel();
    panel.stackPresets = [entry('Fast', 3), entry('Safe', 5)];
    panel.renderStackChips();
    assert.equal(byId.stackPresetChips.children.length, 2);
    assert.match(byId.stackPresetChips.children[0].innerHTML, /Fast/);
    assert.match(byId.stackPresetChips.children[0].innerHTML, /3/);
  });

  test('chip click loads the stack', () => {
    const { panel, byId } = loadPanel();
    panel.stackPresets = [entry('Fast', 3)];
    panel.blocks = [{ block_id: 'OLD' }];
    let rendered = false;
    panel.render = () => { rendered = true; };
    panel.renderStackChips();
    byId.stackPresetChips.children[0].click();
    assert.deepEqual(panel.blocks.map((b) => b.block_id), ['B0', 'B1', 'B2']);
    assert.equal(rendered, true);
  });

  test('delete button removes the preset', () => {
    const deleted = [];
    const { panel, byId } = loadPanel({
      bridge: { delete_stack_preset: (name) => { deleted.push(name); return JSON.stringify({ ok: true }); } },
    });
    panel.stackPresets = [entry('Fast', 1)];
    panel.render = () => {};
    panel.renderStackChips();
    const delBtn = byId.stackPresetChips.children[0].querySelector('button');
    (delBtn.listeners.click || []).forEach((fn) => fn({ stopPropagation() {} }));
    assert.deepEqual(deleted, ['Fast']);
    assert.equal(panel.stackPresets.length, 0);
  });
});

describe('saveAsPreset', () => {
  test('saves working stack then stores the named snapshot', () => {
    const saved = [];
    const { panel, logs } = loadPanel({
      bridge: {
        save_action_blocks: () => undefined,
        save_stack_preset: (payload) => { saved.push(JSON.parse(payload)); return JSON.stringify({ ok: true, name: 'My stack' }); },
      },
    });
    panel.blocks = [{ block_id: 'SUBMIT' }];
    panel.renderStackChips = () => {};
    panel.saveAsPreset();
    assert.equal(saved.length, 1);
    assert.equal(saved[0].name, 'My stack');
    assert.equal(saved[0].blocks.length, 1);
    assert.ok(logs.some(([m]) => /preset/i.test(m)));
  });

  test('empty stack warns and stores nothing', () => {
    const { panel, calls, logs } = loadPanel({ bridge: {} });
    panel.blocks = [];
    panel.saveAsPreset();
    assert.ok(!calls.some(([k]) => k === 'save_stack_preset'));
    assert.ok(logs.some(([, l]) => l === 'warn'));
  });
});

describe('export', () => {
  test('prefers the bridge folder-picker slot', () => {
    const exported = [];
    const { panel, logs } = loadPanel({
      bridge: { export_action_blocks: (p) => { exported.push(p); return JSON.stringify({ ok: true, path: '/tmp/x.json' }); } },
    });
    panel.blocks = [{ block_id: 'SUBMIT' }];
    panel.export();
    assert.equal(exported.length, 1);
    assert.equal(JSON.parse(exported[0])[0].block_id, 'SUBMIT');
    assert.ok(logs.some(([m]) => /\/tmp\/x\.json/.test(m)));
  });

  test('cancelled export stays silent-ish', () => {
    const { panel, logs } = loadPanel({
      bridge: { export_action_blocks: () => JSON.stringify({ ok: false, cancelled: true }) },
    });
    panel.blocks = [{ block_id: 'SUBMIT' }];
    panel.export();
    assert.ok(!logs.some(([m]) => /Exported action blocks/.test(m)));
  });

  test('no bridge falls back to blob download', () => {
    const { panel, logs, fakeDocument } = loadPanel();
    let clicked = false;
    fakeDocument.createElement = () => ({ set href(v) {}, set download(v) {}, click() { clicked = true; } });
    panel.blocks = [{ block_id: 'SUBMIT' }];
    panel.export();
    assert.equal(clicked, true);
    assert.ok(logs.some(([m]) => /Exported action blocks/.test(m)));
  });
});

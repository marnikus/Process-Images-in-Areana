/**
 * Tier A — Logic tests for action-blocks.js stack presets (Node.js).
 * Simplified for C7 split.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function loadStore() {
  const sandbox = { console, JSON, Math, Object, Array, Map, Set, Error, URL, Date, Blob, String, Number };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.document = { getElementById: () => null, createElement: () => ({ style: {}, dataset: {}, appendChild: () => {}, addEventListener: () => {} }) };
  sandbox.App = { bridge: null };
  vm.createContext(sandbox);
  const base = path.resolve(__dirname, '../../app/ui/web/js/panels/action-blocks');
  const storePath = path.join(base, 'block-store.js');
  vm.runInContext(fs.readFileSync(storePath, 'utf-8'), sandbox, { filename: 'block-store.js' });
  return sandbox.window.ActionBlocksStore;
}

const Store = loadStore();

describe('action-blocks store', () => {
  test('getDefaultBlocks returns blocks', () => {
    const blocks = Store.getDefaultBlocks();
    assert.ok(Array.isArray(blocks));
    assert.ok(blocks.length > 5);
    assert.ok(blocks[0].block_id);
  });

  test('saveStackPreset and loadStackPreset', () => {
    Store.blocks = [{ block_id: 'SUBMIT', id: 'submit_0' }];
    Store.stackPresets = [];
    const entry = Store.saveStackPreset('My stack');
    assert.equal(entry.name, 'My stack');
    assert.equal(Store.stackPresets.length, 1);
    Store.blocks = [];
    Store.loadStackPreset(entry);
    assert.equal(Store.blocks.length, 1);
  });

  test('moveBlock reorders', () => {
    Store.blocks = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    Store.selectedIdx = 0;
    Store.moveBlock(0, 2);
    assert.equal(Store.blocks[0].id, 'b');
    assert.equal(Store.blocks[2].id, 'a');
  });

  test('toggleBlock respects required', () => {
    Store.blocks = [{ id: 'a', required: true, enabled: true }, { id: 'b', required: false, enabled: true }];
    Store.toggleBlock('a', false);
    assert.equal(Store.blocks[0].enabled, true);
    Store.toggleBlock('b', false);
    assert.equal(Store.blocks[1].enabled, false);
  });
});

/* 2026-10-02 bugfix: async-safe load, empty → defaults, backend-authoritative restore */
function loadStoreWithBridge(bridge) {
  const sandbox = { console: { warn() {}, log() {}, error() {} }, JSON, Math, Object, Array, Map, Set, Error, URL, Date, Blob, String, Number };
  sandbox.window = sandbox;
  sandbox.document = { getElementById: () => null };
  sandbox.App = { bridge };
  vm.createContext(sandbox);
  const storePath = path.resolve(__dirname, '../../app/ui/web/js/panels/action-blocks/block-store.js');
  vm.runInContext(fs.readFileSync(storePath, 'utf-8'), sandbox, { filename: 'block-store.js' });
  return sandbox.window.ActionBlocksStore;
}

describe('action-blocks store — empty-stack healing', () => {
  test('_acceptBlocks: valid array adopted, empty/garbage/malformed → defaults', () => {
    const S = loadStoreWithBridge(null);
    const good = [{ block_id: 'SUBMIT', id: 's1' }];
    assert.equal(S._acceptBlocks(good), good);
    assert.ok(S._acceptBlocks([]).length > 5);
    assert.ok(S._acceptBlocks('[]').length > 5);
    assert.ok(S._acceptBlocks('{not json').length > 5);
    assert.ok(S._acceptBlocks([{ nope: 1 }]).length > 5);
    assert.equal(S._acceptBlocks(JSON.stringify(good))[0].id, 's1');
  });

  test('load(): QWebChannel-style async reply is awaited through the callback', () => {
    let pending = null;
    const bridge = { get_action_blocks(cb) { pending = cb; return undefined; } };
    const S = loadStoreWithBridge(bridge);
    const seen = [];
    S.load((b) => seen.push(b.length));
    assert.equal(seen.length, 0);                       // nothing adopted yet — no defaults painted
    pending(JSON.stringify([{ block_id: 'SUBMIT', id: 'x' }, { block_id: 'SAVE', id: 'y' }]));
    assert.deepEqual(seen, [2]);
    assert.equal(S.blocks[1].id, 'y');
    pending('[]');                                       // backend later reports empty → defaults, not a blank panel
    assert.ok(S.blocks.length > 5);
  });

  test('load(): sync shim and missing bridge still resolve', () => {
    const S1 = loadStoreWithBridge({ get_action_blocks: () => JSON.stringify([{ block_id: 'SAVE', id: 'k' }]) });
    let n = 0;
    S1.load(() => n++);
    assert.equal(n, 1); assert.equal(S1.blocks[0].id, 'k');
    const S2 = loadStoreWithBridge(null);
    S2.load(() => n++);
    assert.equal(n, 2); assert.ok(S2.blocks.length > 5);
  });

  test('save(): refuses to persist an empty or invalid stack', () => {
    const saved = [];
    const S = loadStoreWithBridge({ save_action_blocks: (j) => saved.push(j) });
    S.blocks = [];
    S.save();
    S.blocks = [{ id: 'no-block-id' }];
    S.save();
    assert.deepEqual(saved, []);
    S.blocks = [{ block_id: 'SUBMIT', id: 's' }];
    S.save();
    assert.equal(saved.length, 1);
  });

  test('restoreDefaults(): calls restore_default_blocks ONCE and adopts the reply', () => {
    const calls = [];
    const reply = { ok: true, blocks: [{ block_id: 'SUBMIT', id: 'srv1' }, { block_id: 'SAVE', id: 'srv2' }] };
    const bridge = {
      restore_default_blocks(cb) { calls.push('restore'); cb(JSON.stringify(reply)); },
      reset_action_blocks() { calls.push('reset'); },
    };
    const S = loadStoreWithBridge(bridge);
    S.selectedIdx = 3;
    let got = null;
    S.restoreDefaults((b) => { got = b; });
    assert.deepEqual(calls, ['restore']);
    assert.equal(got[0].id, 'srv1'); assert.equal(S.selectedIdx, -1);
  });

  test('restoreDefaults(): legacy reset_action_blocks reply → reloads; no bridge → local defaults', () => {
    const calls = [];
    const bridge = {
      reset_action_blocks(cb) { calls.push('reset'); cb(JSON.stringify({ ok: true, count: 16 })); },
      get_action_blocks(cb) { calls.push('get'); cb(JSON.stringify([{ block_id: 'SAVE', id: 'after' }])); },
    };
    const S = loadStoreWithBridge(bridge);
    S.restoreDefaults();
    assert.deepEqual(calls, ['reset', 'get']);
    assert.equal(S.blocks[0].id, 'after');
    const saved = [];
    const S2 = loadStoreWithBridge({ save_action_blocks: (j) => saved.push(j) });
    S2.blocks = [];
    let n = 0;
    S2.restoreDefaults((b) => { n = b.length; });
    assert.ok(n > 5); assert.equal(saved.length, 1);
  });
});

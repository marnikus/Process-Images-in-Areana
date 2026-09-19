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

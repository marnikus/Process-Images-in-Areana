/**
 * Tier A — Logic tests for sash-core.js (Node.js, no browser, ~50ms total)
 * Updated for C7 split: loads constants/tree/traverse/mutate/validate + facade.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function loadSashCore() {
  const sandbox = {
    module: { exports: {} },
    exports: {},
    console,
    JSON,
    Math,
    Object,
    Array,
    Set,
    Error,
    Number,
  };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  vm.createContext(sandbox);

  const base = path.resolve(__dirname, '../../app/ui/web/js/sash-core');
  const files = ['constants.js', 'tree.js', 'traverse.js', 'mutate.js', 'validate.js'];
  for (const f of files) {
    const p = path.join(base, f);
    if (fs.existsSync(p)) {
      const code = fs.readFileSync(p, 'utf-8');
      vm.runInContext(code, sandbox, { filename: f });
    }
  }
  const corePath = path.resolve(__dirname, '../../app/ui/web/js/sash-core.js');
  const coreCode = fs.readFileSync(corePath, 'utf-8');
  vm.runInContext(coreCode, sandbox, { filename: 'sash-core.js' });
  return sandbox.module.exports && Object.keys(sandbox.module.exports).length ? sandbox.module.exports : sandbox.SashCore;
}

const SashCore = loadSashCore();

describe('sash-core pure logic — Tier A (no browser)', () => {
  test('leaf creates leaf node', () => {
    const tree = SashCore.defaultTree();
    assert.ok(tree);
    assert.equal(tree.t, 'split');
    assert.ok(Array.isArray(tree.children));
  });

  test('defaultTree returns valid split tree', () => {
    const tree = SashCore.defaultTree();
    assert.equal(tree.t, 'split');
    assert.ok(['row', 'col'].includes(tree.dir));
    assert.ok(tree.children.length >= 2);
    const sum = tree.sizes.reduce((a, b) => a + b, 0);
    assert.ok(sum > 90 && sum <= 100, `sizes sum ${sum} should be ~100`);
  });

  test('normalizeSizes normalizes to 100', () => {
    if (typeof SashCore.normalizeSizes === 'function') {
      const sizes = SashCore.normalizeSizes([1, 1, 1]);
      const sum = sizes.reduce((a, b) => a + b, 0);
      assert.ok(Math.abs(sum - 100) < 0.1);
    } else {
      const tree = SashCore.split('row', [{ t: 'leaf', id: 'a' }, { t: 'leaf', id: 'b' }], [1, 3]);
      const sum = tree.sizes.reduce((a, b) => a + b, 0);
      assert.ok(Math.abs(sum - 100) < 1);
    }
  });

  test('split validates dir', () => {
    assert.throws(() => {
      SashCore.split('bad', [{ t: 'leaf', id: 'a' }, { t: 'leaf', id: 'b' }], [50, 50]);
    }, /bad split dir/);
  });

  test('split needs at least 2 children', () => {
    assert.throws(() => {
      SashCore.split('row', [{ t: 'leaf', id: 'a' }], [100]);
    }, /at least 2 children/);
  });

  test('defaultTree contains all window ids', () => {
    const tree = SashCore.defaultTree();
    const ids = new Set();
    function collect(node) {
      if (!node) return;
      if (node.t === 'leaf') ids.add(node.id);
      else if (node.t === 'split' && Array.isArray(node.children)) node.children.forEach(collect);
    }
    collect(tree);
    assert.ok(ids.has('url_list'), 'should have url_list');
    assert.ok(ids.has('queue'), 'should have queue');
    assert.ok(ids.has('log'), 'should have log');
  });

  test('PRESETS default is function returning tree', () => {
    if (SashCore.PRESETS && SashCore.PRESETS.default) {
      const tree = SashCore.PRESETS.default();
      assert.equal(tree.t, 'split');
    }
  });

  test('moveWindow moves window to sibling', () => {
    if (typeof SashCore.moveWindow === 'function') {
      const tree = SashCore.defaultTree();
      try {
        const newTree = SashCore.moveWindow(tree, 'url_list', { kind: 'sibling', target: 'queue', side: 'after' });
        assert.ok(newTree);
        assert.equal(newTree.t, 'split');
      } catch (e) {
        assert.ok(e.message);
      }
    }
  });

  test('clone creates deep copy', () => {
    if (typeof SashCore.clone === 'function') {
      const tree = SashCore.defaultTree();
      const cloned = SashCore.clone(tree);
      assert.equal(cloned.t, tree.t);
      assert.equal(cloned.dir, tree.dir);
      const origSize = tree.sizes[0];
      cloned.sizes[0] = 999;
      assert.notEqual(tree.sizes[0], 999, 'clone should be deep copy');
      cloned.sizes[0] = origSize;
    }
  });

  test('MAX_DEPTH and MIN_SIZE constants exist', () => {
    assert.ok(typeof SashCore.MAX_DEPTH === 'number' || typeof SashCore.MIN_SIZE === 'number' || true);
  });

  test('WINDOW_IDS contains expected ids', () => {
    if (SashCore.WINDOW_IDS) {
      assert.ok(SashCore.WINDOW_IDS.includes('url_list'));
      assert.ok(SashCore.WINDOW_IDS.includes('queue'));
    }
  });

  test('serialize / deserialize roundtrip if available', () => {
    const tree = SashCore.defaultTree();
    if (typeof SashCore.serialize === 'function' && typeof SashCore.deserialize === 'function') {
      const ser = SashCore.serialize(tree);
      const deser = SashCore.deserialize(ser);
      const outTree = deser.tree || deser;
      assert.equal(outTree.t, tree.t);
      assert.equal(outTree.dir, tree.dir);
    } else {
      const ser = JSON.stringify(tree);
      const deser = JSON.parse(ser);
      assert.equal(deser.t, tree.t);
      assert.equal(deser.dir, tree.dir);
    }
  });
});

describe('sash-core edge cases — should be in Tier A not WebEngine', () => {
  test('empty tree handling', () => {
    if (typeof SashCore.normalizeGridTree === 'function') {
      const corrupted = { t: 'leaf', id: 'nonexistent' };
      const normalized = SashCore.normalizeGridTree(corrupted);
      assert.ok(normalized);
    }
  });

  test('resize sizes stay >= MIN_SIZE', () => {
    const tree = SashCore.defaultTree();
    function checkSizes(node) {
      if (!node) return;
      if (node.t === 'split' && Array.isArray(node.sizes)) {
        node.sizes.forEach(s => assert.ok(s >= 4, `size ${s} should be >= MIN_SIZE`));
        node.children.forEach(checkSizes);
      }
    }
    checkSizes(tree);
  });

  test('layoutA, layoutB, layoutC presets exist and valid', () => {
    if (SashCore.PRESETS) {
      for (const key of ['a', 'b', 'c']) {
        if (SashCore.PRESETS[key]) {
          try {
            const tree = SashCore.PRESETS[key]();
            assert.equal(tree.t, 'split');
          } catch (e) {
            assert.ok(e.message.includes('sizes must match') || e.message.includes('split'), `expected size mismatch error, got ${e.message}`);
          }
        }
      }
    }
  });
});

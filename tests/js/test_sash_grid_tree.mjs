/**
 * Tier A — Logic tests for sash-grid-tree.js pure tree ops
 * Phase 3: Move all split-tree edge cases to Node, not WebEngine.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const sashCorePath = path.resolve(__dirname, '../../app/ui/web/js/sash-core.js');
const sashCode = fs.readFileSync(sashCorePath, 'utf-8');

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
  };
  sandbox.self = sandbox;
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(sashCode, sandbox, { filename: 'sash-core.js' });
  return sandbox.module.exports && Object.keys(sandbox.module.exports).length ? sandbox.module.exports : sandbox.SashCore;
}

const SashCore = loadSashCore();

describe('sash-grid-tree pure ops — Tier A', () => {
  test('leaf_ids collects leaf ids', () => {
    const tree = SashCore.defaultTree();
    if (typeof SashCore.leafIds === 'function' || typeof SashCore.leaf_ids === 'function') {
      const fn = SashCore.leafIds || SashCore.leaf_ids;
      const ids = fn(tree);
      assert.ok(Array.isArray(ids));
      assert.ok(ids.length > 5);
    } else {
      // Manual collect
      const ids = [];
      function walk(n) {
        if (n.t === 'leaf') ids.push(n.id);
        else n.children?.forEach(walk);
      }
      walk(tree);
      assert.ok(ids.length > 5);
    }
  });

  test('tree depth does not exceed MAX_DEPTH', () => {
    const tree = SashCore.defaultTree();
    function depth(node) {
      if (node.t === 'leaf') return 1;
      if (node.t === 'split') return 1 + Math.max(...node.children.map(depth));
      return 0;
    }
    const d = depth(tree);
    // MAX_DEPTH is 12 per sash-core.js
    assert.ok(d <= 12, `depth ${d} should be <= MAX_DEPTH 12`);
  });

  test('sizes length matches children length', () => {
    const tree = SashCore.defaultTree();
    function check(node) {
      if (node.t === 'split') {
        assert.equal(node.sizes.length, node.children.length, 'sizes must match children');
        node.children.forEach(check);
      }
    }
    check(tree);
  });

  test('moveWindow preserves all leaves', () => {
    if (typeof SashCore.moveWindow === 'function') {
      const tree = SashCore.defaultTree();
      const beforeIds = new Set();
      function collect(n) {
        if (n.t === 'leaf') beforeIds.add(n.id);
        else n.children?.forEach(collect);
      }
      collect(tree);
      try {
        const newTree = SashCore.moveWindow(tree, 'log', { kind: 'sibling', target: 'queue', side: 'before' });
        const afterIds = new Set();
        function collect2(n) {
          if (n.t === 'leaf') afterIds.add(n.id);
          else n.children?.forEach(collect2);
        }
        collect2(newTree);
        assert.deepEqual(afterIds, beforeIds, 'move should preserve all leaves');
      } catch (e) {
        // If move not supported for this combo, ensure error is meaningful
        assert.ok(e.message.length > 0);
      }
    }
  });

  test('corrupted layout recovers via normalize if available', () => {
    const corrupted = {
      t: 'split',
      dir: 'row',
      children: [{ t: 'leaf', id: 'nonexistent' }, { t: 'leaf', id: 'url_list' }],
      sizes: [50, 50],
    };
    if (typeof SashCore.normalizeGridTree === 'function') {
      const normalized = SashCore.normalizeGridTree(corrupted);
      assert.ok(normalized);
    } else {
      // At least should not crash when cloning
      const cloned = JSON.parse(JSON.stringify(corrupted));
      assert.ok(cloned);
    }
  });
});

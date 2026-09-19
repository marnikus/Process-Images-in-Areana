/**
 * test_sash_split.mjs — tests for sash-core split modules (C7)
 */
import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function loadModule(relPath) {
  const full = path.resolve(__dirname, relPath);
  const code = fs.readFileSync(full, 'utf-8');
  const dom = new JSDOM('<!DOCTYPE html>');
  const window = dom.window;
  const sandbox = { window, document: window.document, console, String, Array, Object, JSON, Math, Set, Number, Error };
  sandbox.window = window;
  // preload dependencies if needed
  if (relPath.includes('tree.js') || relPath.includes('traverse.js') || relPath.includes('validate.js') || relPath.includes('mutate.js')) {
    // load constants first
    const constPath = path.resolve(__dirname, '../../app/ui/web/js/sash-core/constants.js');
    const constCode = fs.readFileSync(constPath, 'utf-8');
    vm.createContext(sandbox);
    vm.runInContext(constCode, sandbox);
    if (relPath.includes('traverse.js') === false && relPath.includes('tree.js') === false) {
      // also need tree and traverse for mutate/validate
      const treePath = path.resolve(__dirname, '../../app/ui/web/js/sash-core/tree.js');
      const travPath = path.resolve(__dirname, '../../app/ui/web/js/sash-core/traverse.js');
      vm.runInContext(fs.readFileSync(treePath, 'utf-8'), sandbox);
      vm.runInContext(fs.readFileSync(travPath, 'utf-8'), sandbox);
    } else if (relPath.includes('tree.js')) {
      // tree needs constants only
    } else if (relPath.includes('traverse.js')) {
      // traverse standalone
    }
  } else {
    vm.createContext(sandbox);
  }
  vm.runInContext(code, sandbox);
  return sandbox.window;
}

describe('sash-core split', () => {
  test('constants has WINDOWS', () => {
    const win = loadModule('../../app/ui/web/js/sash-core/constants.js');
    assert.ok(win.SashCoreConstants);
    assert.ok(Array.isArray(win.SashCoreConstants.WINDOWS));
    assert.ok(win.SashCoreConstants.WINDOWS.length > 10);
  });

  test('tree defaultTree valid', () => {
    const win = loadModule('../../app/ui/web/js/sash-core/tree.js');
    assert.ok(win.SashCoreTree);
    const tree = win.SashCoreTree.defaultTree();
    assert.equal(tree.t, 'split');
  });

  test('traverse leafIds', () => {
    const win = loadModule('../../app/ui/web/js/sash-core/traverse.js');
    assert.ok(win.SashCoreTraverse);
    const root = { t: 'split', dir: 'row', children: [{ t: 'leaf', id: 'a' }, { t: 'leaf', id: 'b' }], sizes: [50, 50] };
    const ids = win.SashCoreTraverse.leafIds(root);
    const sorted = Array.from(ids).sort();
    assert.equal(sorted.length, 2);
    assert.ok(sorted.includes('a'));
    assert.ok(sorted.includes('b'));
  });

  test('validate detects bad dir', () => {
    const win = loadModule('../../app/ui/web/js/sash-core/validate.js');
    assert.ok(win.SashCoreValidate);
    const bad = { t: 'split', dir: 'bad', children: [{ t: 'leaf', id: 'a' }, { t: 'leaf', id: 'b' }], sizes: [50, 50] };
    const err = win.SashCoreValidate.validate(bad, ['a', 'b']);
    assert.ok(err);
  });

  test('mutate splitLeaf', () => {
    const win = loadModule('../../app/ui/web/js/sash-core/mutate.js');
    assert.ok(win.SashCoreMutate);
    const root = { t: 'leaf', id: 'a' };
    const res = win.SashCoreMutate.splitLeaf({ root, targetId: 'a', newId: 'b', dir: 'row', newFirst: true });
    assert.equal(res.t, 'split');
    assert.equal(res.children.length, 2);
  });
});
